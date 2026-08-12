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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server, ServerRequestContext

from mcp_logic.categorical_helpers import (
    CategoricalHelpers,
    group_axioms,
    monoid_axioms,
)
from mcp_logic.fragments import (
    FragmentVerdict,
    classify_counterexample,
    classify_fragment,
)
from mcp_logic.hcc_prover import check_contingency

# Import new modules
from mcp_logic.logic_advisor import AdvisorDisabledError, LogicAdvisor
from mcp_logic.mace4_wrapper import Mace4Wrapper
from mcp_logic.smt_solver import check_entailment, check_satisfiable, z3_available
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


# Prover9 announces why it stopped: "------ process 123 exit (sos_empty) ------"
_EXIT_REASON_RE = re.compile(r"exit\s*\(([a-z_]+)\)")

#: The only failure exit that licenses a definitive "does not follow".
#: Resolution is refutation-complete, so an emptied set-of-support means the
#: negated goal is genuinely satisfiable.  Every other exit is a resource
#: limit, which tells us nothing — first-order validity is only
#: semi-decidable (Harrison, *Handbook of Practical Logic*, §7.6, Church's
#: theorem), so "no proof found" is NOT "invalid" unless the search was
#: exhaustive.
_SATURATION_EXIT = "sos_empty"


def _classify_search_failure(output: str) -> dict[str, Any]:
    """Distinguish a genuine non-entailment from giving up.

    Prover9 prints ``SEARCH FAILED`` for both, which previously collapsed
    into a single confident ``unprovable``.  A run that died on
    ``max_megs`` would then be reported as "the conclusion does not
    follow" — a verdict the evidence does not support.

    Args:
        output: Raw Prover9 stdout.

    Returns:
        ``result="unprovable"`` with ``definitive=True`` only when the
        search saturated; otherwise ``result="inconclusive"``.
    """
    match = _EXIT_REASON_RE.search(output)
    exit_reason = match.group(1) if match else "unknown"

    if exit_reason == _SATURATION_EXIT:
        return {
            "result": "unprovable",
            "definitive": True,
            "exit_reason": exit_reason,
            "reason": (
                "Proof search SATURATED: every consequence was derived and no "
                "contradiction arose. The conclusion genuinely does not follow "
                "from the premises."
            ),
            "hint": (
                "Use find_counterexample with the same premises and conclusion "
                "to obtain a concrete model where the premises hold but the "
                "conclusion fails."
            ),
        }

    return {
        "result": "inconclusive",
        "definitive": False,
        "exit_reason": exit_reason,
        "reason": (
            f"Proof search stopped early ({exit_reason}) without exhausting "
            "the search space. This is NOT evidence that the conclusion is "
            "false — first-order validity is only semi-decidable, so an "
            "abandoned search tells us nothing either way."
        ),
        "hint": (
            "Retry with a longer timeout, or call find_counterexample: a "
            "counter-model would settle it in the negative."
        ),
    }


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
                    result = _classify_search_failure(stdout_str)
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


def _annotate_fragment_result(
    result: dict[str, Any],
    verdict: FragmentVerdict,
    *,
    complete_search: bool,
) -> dict[str, Any]:
    """Attach fragment evidence without overstating an incomplete search."""

    result["fragment"] = verdict.fragment
    result["model_bound"] = verdict.model_bound
    result["fragment_reason"] = verdict.reason
    result["decided"] = complete_search and result.get("result") in {
        "model_found",
        "no_model_found",
    }
    if result["decided"] and result.get("result") == "no_model_found":
        result["reason"] = (
            f"No model exists. The complete {verdict.fragment} finite-model "
            f"search exhausted every domain size from 1 through "
            f"{verdict.model_bound}."
        )
        result.pop("hint", None)
        if "interpretation" in result:
            result["interpretation"] = (
                "No counterexample exists. The complete finite-model search "
                f"establishes that the conclusion follows in the "
                f"{verdict.fragment} fragment."
            )
    return result


async def _find_model_with_fragment(
    mace4: Mace4Wrapper,
    premises: list[str],
    domain_size: int | None = None,
    *,
    timeout: int = 60,
    verbose: bool = False,
) -> dict[str, Any]:
    verdict = classify_fragment(premises)
    complete_search = verdict.decidable and domain_size is None
    if complete_search:
        result = await mace4.find_model(
            premises,
            timeout=timeout,
            verbose=verbose,
            max_domain_size=verdict.model_bound,
        )
    else:
        result = await mace4.find_model(
            premises,
            domain_size,
            timeout=timeout,
            verbose=verbose,
        )
    return _annotate_fragment_result(result, verdict, complete_search=complete_search)


async def _find_counterexample_with_fragment(
    mace4: Mace4Wrapper,
    premises: list[str],
    conclusion: str,
    domain_size: int | None = None,
    *,
    timeout: int = 60,
    verbose: bool = False,
) -> dict[str, Any]:
    verdict = classify_counterexample(premises, conclusion)
    complete_search = verdict.decidable and domain_size is None
    if complete_search:
        result = await mace4.find_counterexample(
            premises,
            conclusion,
            timeout=timeout,
            verbose=verbose,
            max_domain_size=verdict.model_bound,
        )
    else:
        result = await mace4.find_counterexample(
            premises,
            conclusion,
            domain_size,
            timeout=timeout,
            verbose=verbose,
        )
    return _annotate_fragment_result(result, verdict, complete_search=complete_search)


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
        return await _find_model_with_fragment(
            self._engine.mace4,
            premises,
            domain_size,
            timeout=timeout,
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
        return await _find_counterexample_with_fragment(
            self._engine.mace4,
            premises,
            conclusion,
            domain_size,
            timeout=timeout,
        )

    async def check_well_formed(self, statements: list[str]) -> dict[str, Any]:
        return validate_formulas(statements)

    async def prove_arithmetic(
        self,
        premises: list[str],
        conclusion: str,
        variables: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not z3_available():
            return {"error": "z3-solver is not installed"}
        return await asyncio.to_thread(
            check_entailment, premises, conclusion, variables or {}
        )

    async def check_satisfiable(
        self,
        constraints: list[str],
        variables: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not z3_available():
            return {"error": "z3-solver is not installed"}
        return await asyncio.to_thread(check_satisfiable, constraints, variables or {})

    async def check_contingency(self, formula: str) -> dict[str, Any]:
        res = check_contingency(formula)
        return {
            "formula": formula,
            "is_contingent": res.is_contingent,
            "is_tautology": res.is_tautology,
            "is_contradiction": res.is_contradiction,
            "message": res.message,
        }


def _ok(payload: Any) -> types.CallToolResult:
    """Wrap a JSON-serialisable payload in a successful CallToolResult.

    Args:
        payload: Any JSON-serialisable value.

    Returns:
        ``CallToolResult`` with a single ``TextContent`` item and
        ``is_error=False``.
    """
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, indent=2))],
        is_error=False,
    )


def _err(payload: Any) -> types.CallToolResult:
    """Wrap a JSON-serialisable error payload in a failed CallToolResult.

    Args:
        payload: Any JSON-serialisable value describing the error.

    Returns:
        ``CallToolResult`` with a single ``TextContent`` item and
        ``is_error=True``.
    """
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, indent=2))],
        is_error=True,
    )


async def _handle_list_tools(
    _ctx: ServerRequestContext[Any],
    _params: types.PaginatedRequestParams | None = None,
) -> types.ListToolsResult:
    """List available MCP tools (SDK v2 handler signature).

    The SDK invokes request handlers positionally as ``(ctx, params)``, so
    both parameters are part of the required shape even though the tool
    catalogue is static. They are underscore-prefixed to say "deliberately
    unused" rather than suppressed with a lint directive.

    Returns:
        ListToolsResult containing the full tool catalogue.
    """

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
                "function, and constant. For recognized BSR or bounded "
                "monadic theories, the tool searches the complete finite "
                "range and returns decided=true; in that case "
                "result='no_model_found' means no model exists at all. "
                "Otherwise it means only that no model was found within "
                "the searched bound. A found model carries a 'vacuity' "
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
                            "automatically and enable complete fragment "
                            "search when a decidable fragment is recognized."
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
                "means the argument is invalid. For recognized BSR or "
                "bounded monadic countermodel theories, decided=true means "
                "the complete finite range was searched; then "
                "'no_model_found' proves that no counterexample exists. "
                "Without decided=true, it means none exists only up to the "
                "searched bound. A found counter-model carries a "
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
                            "automatically and enable complete fragment "
                            "search when a decidable fragment is recognized."
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
            name="prove_arithmetic",
            description=(
                "Prove or refute a claim involving ARITHMETIC, using the Z3 "
                "SMT solver. Use this instead of 'prove' whenever numbers "
                "are involved — Prover9 has no theory of arithmetic and "
                "cannot decide that 2+2=4 or that x+1 > x. Constraints are "
                "SMT-LIB prefix notation: (> x 0), (= y (+ x 1)), "
                "(=> (> x 0) (>= x 1)). Declare every variable in "
                "'variables' with sort Int, Real or Bool. Returns 'proved', "
                "or 'counterexample' with concrete values that break the "
                "claim, or 'unknown' if Z3 could not decide. Example: "
                "premises=['(> x 0)'], conclusion='(> (* x 2) x)', "
                "variables={'x': 'Int'}."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "premises": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "SMT-LIB assertions taken as given",
                    },
                    "conclusion": {
                        "type": "string",
                        "description": "SMT-LIB assertion to prove",
                    },
                    "variables": {
                        "type": "object",
                        "description": (
                            "Variable name -> sort (Int, Real or Bool), "
                            "e.g. {'x': 'Int', 'y': 'Real'}"
                        ),
                    },
                    "functions": {
                        "type": "object",
                        "description": (
                            "Optional uninterpreted functions, name -> "
                            "[arg sorts..., result sort], e.g. "
                            "{'succ': ['Int', 'Int']}"
                        ),
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "Solver timeout in ms (default 10000)",
                    },
                },
                "required": ["premises", "conclusion"],
            },
        ),
        types.Tool(
            name="check_satisfiable",
            description=(
                "Ask Z3 whether a set of ARITHMETIC constraints can all be "
                "true at once, and get a concrete satisfying assignment if "
                "so. Use for consistency checks, puzzles and scheduling-"
                "style problems over numbers. Same SMT-LIB prefix notation "
                "as prove_arithmetic. Returns 'satisfiable' with a model, "
                "'unsatisfiable', or 'unknown'. Example: "
                "constraints=['(> x 0)', '(< x 10)', '(= (mod x 3) 0)'], "
                "variables={'x': 'Int'}."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "SMT-LIB assertions to satisfy together",
                    },
                    "variables": {
                        "type": "object",
                        "description": "Variable name -> sort (Int, Real, Bool)",
                    },
                    "functions": {
                        "type": "object",
                        "description": "Optional uninterpreted function decls",
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "Solver timeout in ms (default 10000)",
                    },
                },
                "required": ["constraints"],
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
    return types.ListToolsResult(tools=tools)


async def _handle_call_tool(
    ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
) -> types.CallToolResult:
    """Dispatch an MCP tool call (SDK v2 handler signature).

    Extracts engine/advisor from ctx.lifespan_context, normalises arguments,
    routes to the appropriate backend. Always returns CallToolResult, never raises.

    Args:
        ctx: Server request context with lifespan_context[engine, advisor].
        params: Validated request parameters from the MCP runtime.

    Returns:
        CallToolResult with is_error=False on success or is_error=True on error.
    """
    name: str = params.name

    try:
        # Inside the try on purpose: unpacking the lifespan context can fail
        # (a mis-wired server, a lifespan that never ran), and this handler
        # promises to return a result rather than raise past the transport.
        engine: LogicEngine = ctx.lifespan_context["engine"]
        advisor: LogicAdvisor = ctx.lifespan_context["advisor"]
        arguments: dict[str, Any] = dict(params.arguments or {})

        if not arguments:
            arguments = {}

        # Normalize arguments globally for all tools
        if "premises" in arguments:
            premises = arguments["premises"]
            if isinstance(premises, dict):
                # Un-wrap if client (like Claude) passed {"item": [...]}
                arguments["premises"] = premises.get("item", list(premises.values()))
            elif isinstance(premises, str):
                arguments["premises"] = [premises]

        if "goal" in arguments and "conclusion" not in arguments:
            arguments["conclusion"] = arguments["goal"]

        if name == "prove":
            conclusion = arguments.get("conclusion")
            if not conclusion:
                return _err(
                    {"error": "Missing required argument: 'conclusion' (or 'goal')"}
                )

            # Validate syntax first
            all_formulas = arguments["premises"] + [conclusion]
            validation = validate_formulas(all_formulas)

            if not validation["valid"]:
                return _ok({"result": "syntax_error", "validation": validation})

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
                    full_formula = f"({premises_joined}) -> ({arguments['conclusion']})"

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
                    return _ok(results)
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
            return _ok(results)

        elif name == "check_well_formed":
            validation = validate_formulas(arguments["statements"])
            return _ok(validation)

        elif name == "find_model":
            if not engine.mace4:
                return _err({"error": "Mace4 not available"})

            domain_size = arguments.get("domain_size")
            result = await _find_model_with_fragment(
                engine.mace4,
                arguments["premises"],
                domain_size,
                verbose=arguments.get("verbose", False),
            )
            return _ok(result)

        elif name == "find_counterexample":
            if not engine.mace4:
                return _err({"error": "Mace4 not available"})

            domain_size = arguments.get("domain_size")
            result = await _find_counterexample_with_fragment(
                engine.mace4,
                arguments["premises"],
                arguments["conclusion"],
                domain_size,
                verbose=arguments.get("verbose", False),
            )
            return _ok(result)

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
            return _ok(result)

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
            return _ok(result)

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
            return _ok(result)

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
                return _err(
                    {
                        "error": res.message,
                        "filtered_out": res.filtered_out_count,
                    }
                )

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
            return _ok(result)

        elif name in {"prove_arithmetic", "check_satisfiable"}:
            if not z3_available():
                return _err(
                    {
                        "error": "z3-solver is not installed",
                        "hint": (
                            "Install it with: uv pip install "
                            "z3-solver — or use prove/find_model "
                            "for non-arithmetic questions."
                        ),
                    }
                )

            shared = {
                "variables": arguments.get("variables") or {},
                "functions": arguments.get("functions") or {},
                "timeout_ms": int(arguments.get("timeout_ms", 10_000)),
            }
            if name == "prove_arithmetic":
                result = await asyncio.to_thread(
                    check_entailment,
                    arguments.get("premises", []),
                    arguments.get("conclusion", ""),
                    **shared,
                )
            else:
                result = await asyncio.to_thread(
                    check_satisfiable,
                    arguments.get("constraints", []),
                    **shared,
                )

            return _ok(result)

        elif name == "ask_logic_advisor":
            question = arguments.get("question", "")
            context = arguments.get("context", "")
            if not question:
                return _err({"error": "Missing required argument: 'question'"})

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

            return _ok(response)

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:  # noqa: BLE001 - this is the transport boundary
        # Deliberately broad. Under SDK v1 the runtime wrapped ANY handler
        # exception into CallToolResult(is_error=True); v2 turns an escaping
        # exception into a JSON-RPC protocol error instead. Catching only
        # (KeyError, ValueError, RuntimeError) would therefore have silently
        # narrowed what the client sees: a TypeError or OSError from a solver
        # subprocess used to come back as a tool error, and would now fail the
        # request at the protocol level. BaseException (CancelledError,
        # KeyboardInterrupt) still propagates, which is correct.
        logger.error("Tool error: %s", e, exc_info=True)
        return _err({"error": str(e), "type": type(e).__name__})


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
        logger.info("Logic advisor enabled (model will lazy-load on first query)")

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        logger.info("Server running with stdio transport")

        # SDK v2: handlers passed as constructor args; lifespan context carries
        # engine + advisor so _handle_call_tool can reach them without closures.
        @asynccontextmanager
        async def _lifespan(_server: Server) -> Any:
            yield {"engine": engine, "advisor": advisor}

        server = Server(
            "logic-manager",
            on_list_tools=_handle_list_tools,
            on_call_tool=_handle_call_tool,
            lifespan=_lifespan,
        )

        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
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
