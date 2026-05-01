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
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

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
from mcp_logic.mace4_wrapper import Mace4Wrapper
from mcp_logic.syntax_validator import validate_formulas
from mcp_logic.vfe_engine import abductive_explain

# Set up logging - basic config, will be re-configured in main()
logger = logging.getLogger("mcp_logic")

# ── Quantifier / FOL patterns for smart routing (CORR-02) ───────────────
# Match genuine quantifiers: 'all x', 'exists y' — but NOT 'all_students'
_QUANTIFIER_RE = re.compile(r"\b(all|exists)\s+[a-z]")
# Match predicate/function calls with arguments: 'p(x)', 'loves(x,y)'
# Excludes quantifier keywords followed by parentheses (handled above).
_PREDICATE_CALL_RE = re.compile(r"\b(?!all\b|exists\b)([a-zA-Z_]\w*)\s*\(")


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

    def _create_input_file(self, premises: List[str], goal: str) -> Path:
        """Create a Prover9 input file"""
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

    async def _run_prover(self, input_path: Path, timeout: int = 60) -> Dict[str, Any]:
        """Run Prover9 directly"""
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
                stdout_str = stdout.decode()
                stderr_str = stderr.decode()

                logger.debug("Prover9 stdout:\n%s", stdout_str)
                if stderr_str:
                    logger.debug("Prover9 stderr:\n%s", stderr_str)

                if "THEOREM PROVED" in stdout_str:
                    proof = stdout_str.split("PROOF =")[1].split("====")[0].strip()
                    return {
                        "result": "proved",
                        "proof": proof,
                        "complete_output": stdout_str,
                    }
                elif "SEARCH FAILED" in stdout_str:
                    return {
                        "result": "unprovable",
                        "reason": "Proof search failed",
                        "complete_output": stdout_str,
                    }
                elif "Fatal error" in stderr_str:
                    return {
                        "result": "error",
                        "reason": "Syntax error",
                        "error": stderr_str,
                    }
                else:
                    return {
                        "result": "error",
                        "reason": "Unexpected output",
                        "output": stdout_str,
                        "error": stderr_str,
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


async def main(prover_path: str, log_level: str = "INFO"):
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
    server = Server("logic-manager")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """List available tools"""
        tools = [
            types.Tool(
                name="prove",
                description="Prove a logical statement using Prover9 or HCC",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "premises": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of logical premises",
                        },
                        "conclusion": {
                            "type": "string",
                            "description": "Statement to prove",
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
                description="Use Mace4 to find a finite model satisfying the given premises",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "premises": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of logical premises",
                        },
                        "domain_size": {
                            "type": "integer",
                            "description": "Optional: specific domain size to search",
                        },
                    },
                    "required": ["premises"],
                },
            ),
            types.Tool(
                name="find_counterexample",
                description="Use Mace4 to find a counterexample",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "premises": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of logical premises",
                        },
                        "conclusion": {
                            "type": "string",
                            "description": "Conclusion to disprove",
                        },
                        "domain_size": {
                            "type": "integer",
                            "description": "Optional: specific domain size to search",
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
                    "Find the VFE-minimizing abductive explanation for an observation from a list of candidates"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "observation": {
                            "type": "string",
                            "description": "The formula string representing the observation",
                        },
                        "candidates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of candidate explanation formulas",
                        },
                        "max_complexity": {
                            "type": "integer",
                            "description": "Optional: maximum complexity bound (default: 20)",
                        },
                    },
                    "required": ["observation", "candidates"],
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
            if name == "prove":
                # Validate syntax first
                all_formulas = arguments["premises"] + [arguments["conclusion"]]
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
                is_propositional = not any(
                    _is_fol_formula(f) for f in all_formulas
                )

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
                        results = {
                            "result": (
                                "proved"
                                if hcc_res.is_tautology
                                else (
                                    "refuted"
                                    if hcc_res.is_contradiction
                                    else "unprovable"
                                )
                            ),
                            "status": hcc_res.message,
                            "method": "HCC (Propositional)",
                            "contingent": hcc_res.is_contingent,
                        }
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
                input_file = engine._create_input_file(
                    arguments["premises"], arguments["conclusion"]
                )
                results = await engine._run_prover(input_file)
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
                    arguments["premises"], domain_size
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
                    arguments["premises"], arguments["conclusion"], domain_size
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
                res = abductive_explain(
                    arguments["observation"],
                    arguments["candidates"],
                    arguments.get("max_complexity", 20),
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
                    "best_explanation": res.best_explanation.formula_str,
                    "vfe_score": res.best_explanation.vfe_score,
                    "complexity": res.best_explanation.complexity,
                    "message": res.message,
                    "ranking": [
                        {
                            "formula": c.formula_str,
                            "score": c.vfe_score,
                            "prior": c.prior,
                        }
                        for c in res.all_candidates
                    ],
                }
                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
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
    args = parser.parse_args()
    asyncio.run(main(args.prover_path, args.log_level))


if __name__ == "__main__":
    cli()
