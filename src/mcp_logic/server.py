"""
Logic MCP Server implementation.

Provides tools for automated theorem proving and model finding using Prover9 and Mace4.
"""

import argparse
import asyncio
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from mcp_logic.categorical_helpers import (
    CategoricalHelpers,
    group_axioms,
    monoid_axioms,
)
from mcp_logic.hcc_prover import check_contingency

# Import new modules
from mcp_logic.logic_advisor import AdvisorDisabledError, LogicAdvisor
from mcp_logic.mace4_wrapper import Mace4Wrapper
from mcp_logic.syntax_validator import normalize_formula, validate_formulas
from mcp_logic.vfe_engine import abductive_explain, abductive_explain_fol

# Set up logging - basic config, will be re-configured in main()
logger = logging.getLogger("mcp_logic")

# ── Quantifier / FOL patterns for smart routing (CORR-02) ───────────────
# Match genuine quantifiers: 'all x', 'exists y' — but NOT 'all_students'
_QUANTIFIER_RE = re.compile(r"\b(all|exists)\s+[a-z]")
# Match predicate/function calls with arguments: 'p(x)', 'loves(x,y)'
# Excludes quantifier keywords followed by parentheses (handled above).
_PREDICATE_CALL_RE = re.compile(r"\b(?!all\b|exists\b)([a-zA-Z_]\w*)\s*\(")


def _extract_proof(output: str) -> str:
    """Extract the human-readable proof block from Prover9 output.

    Prover9 delimits the proof with banner lines of the form
    ``==== PROOF ====`` ... ``==== end of proof ====``.  The previous
    implementation split on the literal ``"PROOF ="`` which collided with
    the row of ``=`` characters in the banner and always produced an empty
    string.  This regex captures everything between the two banners.

    Args:
        output: Raw Prover9 stdout.

    Returns:
        The proof text (clause-by-clause derivation), or "" if not found.
    """
    match = re.search(
        r"=+\s*PROOF\s*=+\s*\n(.*?)\n=+\s*end of proof", output, re.DOTALL
    )
    return match.group(1).strip() if match else ""


def _extract_proof_stats(output: str) -> dict[str, Any]:
    """Pull a few useful numbers out of Prover9 output for a concise summary.

    Args:
        output: Raw Prover9 stdout.

    Returns:
        Dict with any of: ``length`` (proof length), ``level``, ``seconds``.
    """
    stats: dict[str, Any] = {}
    if m := re.search(r"Length of proof is (\d+)", output):
        stats["length"] = int(m.group(1))
    if m := re.search(r"Level of proof is (\d+)", output):
        stats["level"] = int(m.group(1))
    if m := re.search(r"Proof 1 at ([\d.]+)", output):
        stats["seconds"] = float(m.group(1))
    return stats


def _is_fol_formula(formula: str) -> bool:
    """Determine whether a formula is first-order logic (vs. propositional).

    A formula is treated as FOL if it contains:
    - A genuine quantifier (``all x``, ``exists y``) — word boundary +
      space + lowercase variable, OR
    - A predicate/function call with arguments (``p(x)``, ``f(a,b)``).

    Predicate-named atoms like ``all_students(x)`` are correctly recognized
    as predicate calls (FOL) without being confused for quantifiers.

    Pure propositional formulas (``p & q``, ``a -> b``) return False.

    Args:
        formula: The formula string to classify.

    Returns:
        True if the formula should be routed to a FOL prover (Prover9).
    """
    if _QUANTIFIER_RE.search(formula):
        return True
    if _PREDICATE_CALL_RE.search(formula):
        return True
    return False


class LogicEngine:
    """Core logic engine that manages Prover9 and Mace4 execution."""

    def __init__(self, prover_path: str):
        """Initialize connection to Prover9 and Mace4"""
        self.prover_path = Path(prover_path)

        # Initialize Prover9
        self.prover_exe = self.prover_path / "prover9.exe"
        if not self.prover_exe.exists():
            self.prover_exe = self.prover_path / "prover9"
            if not self.prover_exe.exists():
                raise FileNotFoundError(
                    f"Prover9 not found at {self.prover_exe} or with .exe extension"
                )

        logger.debug("Initialized Logic Engine with Prover9 at %s", self.prover_exe)

        # Initialize Mace4
        try:
            self.mace4 = Mace4Wrapper(self.prover_path)
            logger.debug("Mace4 wrapper initialized successfully")
        except FileNotFoundError as e:
            logger.warning("Mace4 not available: %s", e)
            self.mace4 = None

    def create_input_file(self, premises: list[str], goal: str) -> Path:
        """Create a Prover9 input file"""
        premises = [normalize_formula(p) for p in premises]
        goal = normalize_formula(goal)
        content = [
            "formulas(assumptions).",
            *[p if p.endswith(".") else p + "." for p in premises],
            "end_of_list.",
            "",
            "formulas(goals).",
            goal if goal.endswith(".") else goal + ".",
            "end_of_list.",
        ]

        input_content = "\n".join(content)
        logger.debug("Created input file content:\n%s", input_content)

        fd, path = tempfile.mkstemp(suffix=".in", text=True)
        with os.fdopen(fd, "w") as f:
            f.write(input_content)
        return Path(path)

    async def run_prover(
        self, input_path: Path, timeout: int = 60, verbose: bool = False
    ) -> dict[str, Any]:
        """Run Prover9 directly.

        Args:
            input_path: Path to the Prover9 input file.
            timeout: Wall-clock timeout in seconds.
            verbose: When True, include the full raw Prover9 output under
                ``complete_output``.  When False (default), only a concise,
                agent-friendly summary is returned to avoid flooding the
                context with banner text.

        Returns:
            Result dict.  On success: ``result="proved"``, ``proof`` (clean
            derivation), and ``stats``.  On failure: ``result`` plus a
            ``hint`` suggesting a next step.
        """
        try:
            logger.debug("Running Prover9 with input file: %s", input_path)

            # Set working directory to Prover9 directory
            cwd = str(self.prover_exe.parent)

            # Start the process
            process = await asyncio.create_subprocess_exec(
                str(self.prover_exe),
                "-f",
                str(input_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                # Wait for completion with timeout
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
                # Prover9 echoes the input back verbatim, so non-UTF-8 bytes
                # in a malformed formula land in stdout.  Never let that
                # crash the run — surface the syntax error instead.
                stdout_str = stdout.decode("utf-8", errors="replace")
                stderr_str = stderr.decode("utf-8", errors="replace")

                logger.debug("Prover9 stdout:\n%s", stdout_str)
                if stderr_str:
                    logger.debug("Prover9 stderr:\n%s", stderr_str)

                if "THEOREM PROVED" in stdout_str:
                    result = {
                        "result": "proved",
                        "proof": _extract_proof(stdout_str),
                        "stats": _extract_proof_stats(stdout_str),
                    }
                    if verbose:
                        result["complete_output"] = stdout_str
                    return result
                elif "SEARCH FAILED" in stdout_str:
                    result = {
                        "result": "unprovable",
                        "reason": (
                            "Proof search exhausted without finding a proof. "
                            "The conclusion does not follow from the premises, "
                            "or the premises are too weak."
                        ),
                        "hint": (
                            "Use find_counterexample with the same premises and "
                            "conclusion to obtain a concrete model where the "
                            "premises hold but the conclusion fails."
                        ),
                    }
                    if verbose:
                        result["complete_output"] = stdout_str
                    return result
                elif "Fatal error" in stderr_str or "Fatal error" in stdout_str:
                    return {
                        "result": "error",
                        "reason": "Prover9 syntax/processing error",
                        "error": (stderr_str or stdout_str).strip()[-1000:],
                        "hint": (
                            "Check formula syntax with check_well_formed. Common "
                            "issues: unbalanced parens, missing quantifier scope "
                            "'all x (...)', or empty argument lists."
                        ),
                    }
                else:
                    return {
                        "result": "error",
                        "reason": "Unexpected Prover9 output",
                        "output": stdout_str.strip()[-1000:],
                        "error": stderr_str.strip()[-500:],
                    }

            except asyncio.TimeoutError:
                logger.error("Proof search timed out after %d seconds", timeout)
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass
                return {
                    "result": "timeout",
                    "reason": f"Proof search exceeded {timeout} seconds",
                }

        except (OSError, ValueError) as e:
            logger.error("Prover error: %s", e)
            return {"result": "error", "reason": str(e)}
        finally:
            try:
                input_path.unlink()  # Clean up temp file
            except (FileNotFoundError, PermissionError, OSError):
                pass  # Temp file cleanup failed, not critical


class _SolverBridge:
    """Adapts LogicEngine + Mace4 + HCC into the SolverBackend protocol.

    This lets the LogicAdvisor call the real solver infrastructure without
    importing or knowing about the engine internals.
    """

    def __init__(self, engine: LogicEngine) -> None:
        self._engine = engine

    async def prove(
        self,
        premises: list[str],
        conclusion: str,
        *,
        timeout: int = 60,
    ) -> dict[str, Any]:
        input_file = self._engine.create_input_file(premises, conclusion)
        return await self._engine.run_prover(input_file, timeout=timeout)

    async def find_model(
        self,
        premises: list[str],
        *,
        domain_size: int | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        if not self._engine.mace4:
            return {"error": "Mace4 not available"}
        return await self._engine.mace4.find_model(
            premises, domain_size, timeout=timeout
        )

    async def find_counterexample(
        self,
        premises: list[str],
        conclusion: str,
        *,
        domain_size: int | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        if not self._engine.mace4:
            return {"error": "Mace4 not available"}
        return await self._engine.mace4.find_counterexample(
            premises, conclusion, domain_size, timeout=timeout
        )

    async def check_well_formed(
        self, statements: list[str]
    ) -> dict[str, Any]:
        return validate_formulas(statements)

    async def check_contingency(self, formula: str) -> dict[str, Any]:
        res = check_contingency(formula)
        return {
            "formula": formula,
            "is_contingent": res.is_contingent,
            "is_tautology": res.is_tautology,
            "is_contradiction": res.is_contradiction,
            "message": res.message,
        }


async def main(
    prover_path: str,
    log_level: str = "INFO",
    model_path: str | None = None,
    no_advisor: bool = False,
):
    """Start the MCP Logic Server."""
    # Configure logging
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    logging.basicConfig(level=numeric_level, force=True)
    logger.info(
        "Starting Logic MCP Server with Prover9/Mace4 at: %s (Log Level: %s)",
        prover_path,
        log_level.upper(),
    )

    engine = LogicEngine(prover_path)

    # Wire up the logic advisor (agentic solver with onboard LLM).
    solver_bridge = _SolverBridge(engine)
    advisor = LogicAdvisor(
        solver=solver_bridge,
        model_path=model_path,
        enabled=not no_advisor,
    )
    if no_advisor:
        logger.info("Logic advisor is DISABLED (--no-advisor flag)")
    else:
        logger.info(
            "Logic advisor enabled (model will lazy-load on first query)"
        )

    server = Server("logic-manager")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """List available tools"""
        tools = [
            types.Tool(
                name="prove",
                description=(
                    "Prove that a conclusion follows from premises. Automatically "
                    "routes pure propositional problems to a fast analytic checker "
                    "(HCC) and first-order problems (quantifiers like 'all x', "
                    "'exists y', or predicates with arguments like p(x)) to "
                    "Prover9. Returns result='proved' with the derivation, or "
                    "result='unprovable' with a hint to try find_counterexample. "
                    "Syntax: -> (implies), <-> (iff), & (and), | (or), ~ (not); "
                    "quantifiers must scope with parens, e.g. 'all x (man(x) -> "
                    "mortal(x))'."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "premises": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Assumptions, each a well-formed formula string. "
                                "May be an empty list to prove a logical truth."
                            ),
                        },
                        "conclusion": {
                            "type": "string",
                            "description": "The single statement to prove.",
                        },
                        "verbose": {
                            "type": "boolean",
                            "description": (
                                "If true, include the full raw Prover9 output. "
                                "Default false (concise proof + stats only)."
                            ),
                        },
                    },
                    "required": ["premises", "conclusion"],
                },
            ),
            types.Tool(
                name="check_well_formed",
                description="Check if logical statements are well-formed",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "statements": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Logical statements to check",
                        }
                    },
                    "required": ["statements"],
                },
            ),
            types.Tool(
                name="find_model",
                description=(
                    "Find a concrete finite model (a world) in which all the "
                    "given premises are simultaneously true, using Mace4. Use "
                    "this to check that a set of axioms is satisfiable / "
                    "consistent, or to see an example structure. Returns the "
                    "domain size and the interpretation of each predicate, "
                    "function, and constant. result='no_model_found' means no "
                    "model exists up to the domain bound (premises may be "
                    "contradictory). A found model carries a 'vacuity' "
                    "assessment; a degenerate empty-world model (every "
                    "predicate false everywhere) is flagged with a top-level "
                    "'warning' and only VACUOUSLY satisfies universal "
                    "conditionals — assert existence (e.g. 'exists x (P(x))') "
                    "and re-check before calling the axioms consistent."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "premises": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Formulas that must all hold in the model.",
                        },
                        "domain_size": {
                            "type": "integer",
                            "description": (
                                "Exact domain size to search. Omit to scan sizes "
                                "2..10 automatically."
                            ),
                        },
                        "verbose": {
                            "type": "boolean",
                            "description": "Include raw Mace4 output. Default false.",
                        },
                    },
                    "required": ["premises"],
                },
            ),
            types.Tool(
                name="find_counterexample",
                description=(
                    "Show that a conclusion does NOT follow from the premises by "
                    "finding a model where every premise is true but the "
                    "conclusion is false (via Mace4). This is the natural "
                    "complement to 'prove': if prove returns 'unprovable', call "
                    "this to get the concrete counterexample. result='model_found' "
                    "means the argument is invalid; 'no_model_found' means none "
                    "exists up to the domain bound (the argument may be valid — "
                    "confirm with prove). A found counter-model carries a "
                    "'vacuity' assessment; an empty-world counter-model is "
                    "flagged with a 'warning' and exhibits no real instance "
                    "where the premises hold and the conclusion fails."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "premises": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Assumptions held true in the search.",
                        },
                        "conclusion": {
                            "type": "string",
                            "description": "The statement to falsify.",
                        },
                        "domain_size": {
                            "type": "integer",
                            "description": (
                                "Exact domain size to search. Omit to scan sizes "
                                "2..10 automatically."
                            ),
                        },
                        "verbose": {
                            "type": "boolean",
                            "description": "Include raw Mace4 output. Default false.",
                        },
                    },
                    "required": ["premises", "conclusion"],
                },
            ),
            types.Tool(
                name="verify_commutativity",
                description="Verify categorical diagram commutativity",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path_a": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of morphism names in first path",
                        },
                        "path_b": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of morphism names in second path",
                        },
                        "object_start": {"type": "string"},
                        "object_end": {"type": "string"},
                        "with_category_axioms": {"type": "boolean"},
                    },
                    "required": ["path_a", "path_b", "object_start", "object_end"],
                },
            ),
            types.Tool(
                name="get_category_axioms",
                description="Get FOL axioms for category theory (category, functor, group, etc.)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "concept": {
                            "type": "string",
                            "enum": [
                                "category",
                                "functor",
                                "natural-transformation",
                                "monoid",
                                "group",
                            ],
                            "description": "Which concept's axioms to retrieve",
                        },
                        "functor_name": {
                            "type": "string",
                            "description": "For functor axioms: name of the functor (default: F)",
                        },
                    },
                    "required": ["concept"],
                },
            ),
            types.Tool(
                name="check_contingency",
                description="Check if a classical propositional formula is truth-functionally contingent using HCC",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "formula": {
                            "type": "string",
                            "description": "The propositional formula string to check",
                        }
                    },
                    "required": ["formula"],
                },
            ),
            types.Tool(
                name="abductive_explain",
                description=(
                    "Inference to the best explanation. Given an observation and "
                    "candidate hypotheses, returns the simplest candidate that — "
                    "together with an optional background theory — logically "
                    "entails the observation and stays consistent. Each result is "
                    "flagged with 'explains' (true = it actually entails the "
                    "observation). For a real explanation, pass a 'background' "
                    "theory linking causes to the observation, e.g. "
                    "observation='wet_grass', candidates=['rained','sprinkler'], "
                    "background=['rained -> wet_grass','sprinkler -> wet_grass']. "
                    "Propositional and first-order inputs are both accepted: the "
                    "tool auto-detects quantifiers/predicate calls and routes "
                    "first-order cases to Prover9 (entailment) + Mace4 "
                    "(consistency), e.g. observation='mortal(socrates)', "
                    "candidates=['man(socrates)'], background=['all x (man(x) -> "
                    "mortal(x))']. The response 'logic' field reports which path "
                    "was used. Ranking blends logical adequacy with Occam "
                    "simplicity (VFE)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "observation": {
                            "type": "string",
                            "description": (
                                "The formula that was observed (propositional or "
                                "first-order)."
                            ),
                        },
                        "candidates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Candidate explanation formulas to rank.",
                        },
                        "background": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Optional background theory (domain rules) used to "
                                "decide whether a candidate entails the observation."
                            ),
                        },
                        "max_complexity": {
                            "type": "integer",
                            "description": "Maximum candidate complexity (default 20).",
                        },
                    },
                    "required": ["observation", "candidates"],
                },
            ),
            types.Tool(
                name="ask_logic_advisor",
                description=(
                    "Ask the onboard logic reasoning LLM to solve a logic "
                    "problem END-TO-END. You pose a natural-language question "
                    "and the advisor automatically: (1) formalizes it into "
                    "Prover9/Mace4 syntax, (2) runs the appropriate solver "
                    "(prove, find_model, find_counterexample, etc.), and "
                    "(3) interprets the result in plain English. Use this "
                    "when you want a complete solution without manually "
                    "constructing FOL formulas. Examples: 'Is it true that "
                    "if all humans are mortal and Socrates is human, then "
                    "Socrates is mortal?', 'Find a model where there exist "
                    "at least two distinct elements and every element has a "
                    "successor', 'Is the formula (P -> Q) <-> (-Q -> -P) a "
                    "tautology?'. For direct solver access with your own "
                    "formulas, use prove/find_model/find_counterexample "
                    "instead."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": (
                                "Your logic question in natural language. Be "
                                "as specific as possible about what you want "
                                "to prove, check, or find."
                            ),
                        },
                        "context": {
                            "type": "string",
                            "description": (
                                "Optional additional context: background "
                                "knowledge, constraints, domain-specific "
                                "definitions, or a previous solver result "
                                "you want debugged."
                            ),
                        },
                    },
                    "required": ["question"],
                },
            ),
        ]
        return tools

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Handle tool execution requests"""
        try:
            if not arguments:
                arguments = {}

            # Normalize arguments globally for all tools
            if "premises" in arguments:
                premises = arguments["premises"]
                if isinstance(premises, dict):
                    # Un-wrap if client (like Claude) passed {"item": [...]}
                    arguments["premises"] = premises.get(
                        "item", list(premises.values())
                    )
                elif isinstance(premises, str):
                    arguments["premises"] = [premises]

            if "goal" in arguments and "conclusion" not in arguments:
                arguments["conclusion"] = arguments["goal"]

            if name == "prove":
                conclusion = arguments.get("conclusion")
                if not conclusion:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "error": "Missing required argument: 'conclusion' (or 'goal')"
                                },
                                indent=2,
                            ),
                        )
                    ]

                # Validate syntax first
                all_formulas = arguments["premises"] + [conclusion]
                validation = validate_formulas(all_formulas)

                if not validation["valid"]:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {"result": "syntax_error", "validation": validation},
                                indent=2,
                            ),
                        )
                    ]

                # Smart Routing: Check if propositional (CORR-02)
                is_propositional = not any(_is_fol_formula(f) for f in all_formulas)

                if is_propositional:
                    logger.info("Routing propositional proof to HCC")
                    # Construct (P1 & P2 & ...) -> G
                    if not arguments["premises"]:
                        full_formula = arguments["conclusion"]
                    else:
                        premises_joined = " & ".join(
                            [f"({p})" for p in arguments["premises"]]
                        )
                        full_formula = (
                            f"({premises_joined}) -> ({arguments['conclusion']})"
                        )

                    try:
                        hcc_res = check_contingency(full_formula)
                        if hcc_res.is_tautology:
                            results = {
                                "result": "proved",
                                "status": (
                                    "Valid: the conclusion is true in every "
                                    "model of the premises (the implication is "
                                    "a tautology)."
                                ),
                            }
                        elif hcc_res.is_contradiction:
                            results = {
                                "result": "refuted",
                                "status": (
                                    "The premises are mutually contradictory, so "
                                    "they prove anything trivially (and their "
                                    "negation holds in no model)."
                                ),
                            }
                        else:
                            results = {
                                "result": "unprovable",
                                "status": (
                                    "Invalid: the conclusion does not follow. "
                                    "There is at least one assignment making the "
                                    "premises true and the conclusion false."
                                ),
                                "hint": (
                                    "Use check_contingency on the implication, or "
                                    "find_counterexample, to inspect the falsifying "
                                    "assignment."
                                ),
                            }
                        results["method"] = "HCC (propositional)"
                        return [
                            types.TextContent(
                                type="text", text=json.dumps(results, indent=2)
                            )
                        ]
                    except ValueError as e:
                        logger.warning(
                            "HCC routing failed, falling back to Prover9: %s",
                            e,
                            exc_info=True,
                        )

                # Run proof with Prover9
                input_file = engine.create_input_file(
                    arguments["premises"], arguments["conclusion"]
                )
                results = await engine.run_prover(
                    input_file, verbose=arguments.get("verbose", False)
                )
                results["method"] = "Prover9 (FOL)"
                return [
                    types.TextContent(type="text", text=json.dumps(results, indent=2))
                ]

            elif name == "check_well_formed":
                validation = validate_formulas(arguments["statements"])
                return [
                    types.TextContent(
                        type="text", text=json.dumps(validation, indent=2)
                    )
                ]

            elif name == "find_model":
                if not engine.mace4:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps({"error": "Mace4 not available"}),
                        )
                    ]

                domain_size = arguments.get("domain_size")
                result = await engine.mace4.find_model(
                    arguments["premises"],
                    domain_size,
                    verbose=arguments.get("verbose", False),
                )
                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
                ]

            elif name == "find_counterexample":
                if not engine.mace4:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps({"error": "Mace4 not available"}),
                        )
                    ]

                domain_size = arguments.get("domain_size")
                result = await engine.mace4.find_counterexample(
                    arguments["premises"],
                    arguments["conclusion"],
                    domain_size,
                    verbose=arguments.get("verbose", False),
                )
                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
                ]

            elif name == "verify_commutativity":
                helpers = CategoricalHelpers()
                premises, conclusion = helpers.verify_commutativity(
                    arguments["path_a"],
                    arguments["path_b"],
                    arguments["object_start"],
                    arguments["object_end"],
                )

                # Add category axioms if requested
                if arguments.get("with_category_axioms", True):
                    cat_axioms = helpers.category_axioms()
                    premises = cat_axioms + premises

                result = {
                    "premises": premises,
                    "conclusion": conclusion,
                    "note": "Use the 'prove' tool to verify commutativity",
                }
                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
                ]

            elif name == "get_category_axioms":
                helpers = CategoricalHelpers()
                concept = arguments["concept"]

                if concept == "category":
                    axioms = helpers.category_axioms()
                elif concept == "functor":
                    functor_name = arguments.get("functor_name", "F")
                    axioms = helpers.functor_axioms(functor_name)
                elif concept == "natural-transformation":
                    functor_f = arguments.get("functor_f", "F")
                    functor_g = arguments.get("functor_g", "G")
                    component = arguments.get("component", "alpha")
                    axioms = helpers.natural_transformation_condition(
                        functor_f, functor_g, component
                    )
                elif concept == "monoid":
                    axioms = monoid_axioms()
                elif concept == "group":
                    axioms = group_axioms()
                else:
                    axioms = []

                result = {"concept": concept, "axioms": axioms}
                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
                ]

            elif name == "check_contingency":
                res = check_contingency(arguments["formula"])
                # Simplify trace for output
                simple_trace = [
                    f"{s.rule}: {s.formula}" for s in res.proof_trace if s.formula
                ]
                result = {
                    "formula": arguments["formula"],
                    "is_contingent": res.is_contingent,
                    "is_tautology": res.is_tautology,
                    "is_contradiction": res.is_contradiction,
                    "message": res.message,
                    "proof_trace_summary": simple_trace,
                }
                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
                ]

            elif name == "abductive_explain":
                observation = arguments["observation"]
                candidates = arguments["candidates"]
                background = arguments.get("background") or []
                max_complexity = arguments.get("max_complexity", 20)

                # Smart routing: if the observation, any candidate, or any
                # background formula is first-order, use the Prover9/Mace4
                # path; otherwise stay on the fast propositional HCC path.
                all_formulas = [observation, *candidates, *background]
                is_fol = any(_is_fol_formula(f) for f in all_formulas)

                if is_fol:
                    # Per-candidate FOL checks get a short timeout to keep the
                    # overall call responsive even with several candidates.
                    fol_timeout = 10

                    async def _prove_fn(premises: list[str], conclusion: str) -> bool:
                        f = engine.create_input_file(premises, conclusion)
                        r = await engine.run_prover(f, timeout=fol_timeout)
                        return r.get("result") == "proved"

                    async def _model_fn(premises: list[str]) -> bool:
                        if engine.mace4 is None:
                            # No model finder: skip the consistency filter.
                            return True
                        r = await engine.mace4.find_model(premises, timeout=fol_timeout)
                        return r.get("result") == "model_found"

                    res = await abductive_explain_fol(
                        observation,
                        candidates,
                        _prove_fn,
                        _model_fn,
                        max_complexity,
                        background,
                    )
                else:
                    res = abductive_explain(
                        observation,
                        candidates,
                        max_complexity,
                        background,
                    )
                if not res.best_explanation:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "error": res.message,
                                    "filtered_out": res.filtered_out_count,
                                },
                                indent=2,
                            ),
                        )
                    ]

                result = {
                    "logic": "first_order" if is_fol else "propositional",
                    "best_explanation": res.best_explanation.formula_str,
                    "explains_observation": res.best_explanation.explains,
                    "vfe_score": res.best_explanation.vfe_score,
                    "complexity": res.best_explanation.complexity,
                    "message": res.message,
                    "ranking": [
                        {
                            "formula": c.formula_str,
                            "explains": c.explains,
                            "score": c.vfe_score,
                            "prior": c.prior,
                        }
                        for c in res.all_candidates
                    ],
                }
                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
                ]

            elif name == "ask_logic_advisor":
                question = arguments.get("question", "")
                context = arguments.get("context", "")
                if not question:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                {"error": "Missing required argument: 'question'"},
                                indent=2,
                            ),
                        )
                    ]

                try:
                    result = await advisor.solve(question, context)
                    response = {
                        "answer": result.answer,
                        # False means the solver did NOT return a verdict —
                        # the answer is not machine-checked and must not be
                        # presented to the user as a proof.
                        "verified": result.verified,
                        "formalization": result.formalization,
                        "solver_output": result.solver_output,
                        "steps": result.steps,
                    }
                    if not result.verified:
                        response["warning"] = (
                            "UNVERIFIED: the solver returned no verdict. Do "
                            "not present this as a proved result."
                        )
                except AdvisorDisabledError as e:
                    response = {
                        "error": str(e),
                        "hint": (
                            "The onboard logic advisor LLM is disabled. "
                            "Restart the server without --no-advisor to "
                            "enable it, or use the prove/find_model tools "
                            "directly with your own FOL formulas."
                        ),
                    }

                return [
                    types.TextContent(
                        type="text", text=json.dumps(response, indent=2)
                    )
                ]

            else:
                raise ValueError(f"Unknown tool: {name}")

        except (KeyError, ValueError, RuntimeError) as e:
            logger.error("Tool error: %s", e, exc_info=True)
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": str(e), "type": type(e).__name__}),
                )
            ]

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        logger.info("Server running with stdio transport")
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="logic",
                server_version="0.2.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def cli():
    """CLI entry point for the logic server."""
    parser = argparse.ArgumentParser(description="MCP Logic Server")
    parser.add_argument(
        "--prover-path", type=str, required=True, help="Path to Prover9/Mace4 binaries"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level (default: INFO)",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        default=None,
        help=(
            "Path to a GGUF model file for the logic advisor. "
            "If omitted, TwIL-LM3-Q8_0 is auto-downloaded on first use."
        ),
    )
    parser.add_argument(
        "--no-advisor",
        action="store_true",
        default=False,
        help="Disable the onboard logic advisor LLM entirely.",
    )
    args = parser.parse_args()
    asyncio.run(
        main(
            args.prover_path,
            args.log_level,
            model_path=args.model_path,
            no_advisor=args.no_advisor,
        )
    )


if __name__ == "__main__":
    cli()
