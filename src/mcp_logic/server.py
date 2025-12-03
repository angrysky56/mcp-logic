import logging
import os
import subprocess
import tempfile
import argparse
import asyncio
import json
from typing import Any, List, Dict
from pathlib import Path
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio

# Import new modules
from mcp_logic.mace4_wrapper import Mace4Wrapper
from mcp_logic.syntax_validator import validate_formulas
from mcp_logic.categorical_helpers import CategoricalHelpers

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("mcp_logic")


class LogicEngine:
    def __init__(self, prover_path: str):
        """Initialize connection to Prover9 and Mace4"""
        self.prover_path = Path(prover_path)

        # Initialize Prover9
        self.prover_exe = self.prover_path / "prover9.exe"
        if not self.prover_exe.exists():
            self.prover_exe = self.prover_path / "prover9"
            if not self.prover_exe.exists():
                raise FileNotFoundError(f"Prover9 not found at {self.prover_exe} or with .exe extension")

        logger.debug(f"Initialized Logic Engine with Prover9 at {self.prover_exe}")

        # Initialize Mace4
        try:
            self.mace4 = Mace4Wrapper(self.prover_path)
            logger.debug("Mace4 wrapper initialized successfully")
        except FileNotFoundError as e:
            logger.warning(f"Mace4 not available: {e}")
            self.mace4 = None

    def _create_input_file(self, premises: List[str], goal: str) -> Path:
        """Create a Prover9 input file"""
        content = ["formulas(assumptions).", *[p if p.endswith(".") else p + "." for p in premises], "end_of_list.", "", "formulas(goals).", goal if goal.endswith(".") else goal + ".", "end_of_list."]

        input_content = "\n".join(content)
        logger.debug(f"Created input file content:\n{input_content}")

        fd, path = tempfile.mkstemp(suffix=".in", text=True)
        with os.fdopen(fd, "w") as f:
            f.write(input_content)
        return Path(path)

    def _run_prover(self, input_path: Path, timeout: int = 60) -> Dict[str, Any]:
        """Run Prover9 directly"""
        try:
            logger.debug(f"Running Prover9 with input file: {input_path}")

            # Set working directory to Prover9 directory
            cwd = str(self.prover_exe.parent)
            result = subprocess.run([str(self.prover_exe), "-f", str(input_path)], capture_output=True, text=True, timeout=timeout, cwd=cwd)

            logger.debug(f"Prover9 stdout:\n{result.stdout}")
            if result.stderr:
                logger.debug(f"Prover9 stderr:\n{result.stderr}")

            if "THEOREM PROVED" in result.stdout:
                proof = result.stdout.split("PROOF =")[1].split("====")[0].strip()
                return {"result": "proved", "proof": proof, "complete_output": result.stdout}
            elif "SEARCH FAILED" in result.stdout:
                return {"result": "unprovable", "reason": "Proof search failed", "complete_output": result.stdout}
            elif "Fatal error" in result.stderr:
                return {"result": "error", "reason": "Syntax error", "error": result.stderr}
            else:
                return {"result": "error", "reason": "Unexpected output", "output": result.stdout, "error": result.stderr}
        except subprocess.TimeoutExpired:
            logger.error(f"Proof search timed out after {timeout} seconds")
            return {"result": "timeout", "reason": f"Proof search exceeded {timeout} seconds"}
        except Exception as e:
            logger.error(f"Prover error: {e}")
            return {"result": "error", "reason": str(e)}
        finally:
            try:
                input_path.unlink()  # Clean up temp file
            except (FileNotFoundError, PermissionError, OSError):
                pass  # Temp file cleanup failed, not critical


async def main(prover_path: str):
    logger.info(f"Starting Logic MCP Server with Prover9/Mace4 at: {prover_path}")

    engine = LogicEngine(prover_path)
    server = Server("logic-manager")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """List available tools"""
        tools = [
            types.Tool(
                name="prove",
                description="Prove a logical statement using Prover9",
                inputSchema={
                    "type": "object",
                    "properties": {"premises": {"type": "array", "items": {"type": "string"}, "description": "List of logical premises"}, "conclusion": {"type": "string", "description": "Statement to prove"}},
                    "required": ["premises", "conclusion"],
                },
            ),
            types.Tool(
                name="check-well-formed",
                description="Check if logical statements are well-formed with detailed syntax validation",
                inputSchema={
                    "type": "object",
                    "properties": {"statements": {"type": "array", "items": {"type": "string"}, "description": "Logical statements to check"}},
                    "required": ["statements"],
                },
            ),
            types.Tool(
                name="find-model",
                description="Use Mace4 to find a finite model satisfying the given premises",
                inputSchema={
                    "type": "object",
                    "properties": {"premises": {"type": "array", "items": {"type": "string"}, "description": "List of logical premises"}, "domain_size": {"type": "integer", "description": "Optional: specific domain size to search (default: incrementally search 2-10)"}},
                    "required": ["premises"],
                },
            ),
            types.Tool(
                name="find-counterexample",
                description="Use Mace4 to find a counterexample showing the conclusion doesn't follow from premises",
                inputSchema={
                    "type": "object",
                    "properties": {"premises": {"type": "array", "items": {"type": "string"}, "description": "List of logical premises"}, "conclusion": {"type": "string", "description": "Conclusion to disprove"}, "domain_size": {"type": "integer", "description": "Optional: specific domain size to search"}},
                    "required": ["premises", "conclusion"],
                },
            ),
            types.Tool(
                name="verify-commutativity",
                description="Verify that a categorical diagram commutes by generating FOL premises and conclusion",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path_a": {"type": "array", "items": {"type": "string"}, "description": "List of morphism names in first path"},
                        "path_b": {"type": "array", "items": {"type": "string"}, "description": "List of morphism names in second path"},
                        "object_start": {"type": "string", "description": "Starting object"},
                        "object_end": {"type": "string", "description": "Ending object"},
                        "with_category_axioms": {"type": "boolean", "description": "Include basic category theory axioms (default: true)"},
                    },
                    "required": ["path_a", "path_b", "object_start", "object_end"],
                },
            ),
            types.Tool(
                name="get-category-axioms",
                description="Get FOL axioms for category theory concepts (category, functor, natural transformation)",
                inputSchema={
                    "type": "object",
                    "properties": {"concept": {"type": "string", "enum": ["category", "functor", "natural-transformation", "monoid", "group"], "description": "Which concept's axioms to retrieve"}, "functor_name": {"type": "string", "description": "For functor axioms: name of the functor (default: F)"}},
                    "required": ["concept"],
                },
            ),
        ]
        return tools

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Handle tool execution requests"""
        try:
            if name == "prove":
                # Validate syntax first
                all_formulas = arguments["premises"] + [arguments["conclusion"]]
                validation = validate_formulas(all_formulas)

                if not validation["valid"]:
                    return [types.TextContent(type="text", text=json.dumps({"result": "syntax_error", "validation": validation}, indent=2))]

                # Run proof
                input_file = engine._create_input_file(arguments["premises"], arguments["conclusion"])
                results = engine._run_prover(input_file)
                return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

            elif name == "check-well-formed":
                validation = validate_formulas(arguments["statements"])
                return [types.TextContent(type="text", text=json.dumps(validation, indent=2))]

            elif name == "find-model":
                if not engine.mace4:
                    return [types.TextContent(type="text", text=json.dumps({"error": "Mace4 not available"}))]

                domain_size = arguments.get("domain_size")
                result = engine.mace4.find_model(arguments["premises"], domain_size)
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "find-counterexample":
                if not engine.mace4:
                    return [types.TextContent(type="text", text=json.dumps({"error": "Mace4 not available"}))]

                domain_size = arguments.get("domain_size")
                result = engine.mace4.find_counterexample(arguments["premises"], arguments["conclusion"], domain_size)
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "verify-commutativity":
                helpers = CategoricalHelpers()
                premises, conclusion = helpers.verify_commutativity(arguments["path_a"], arguments["path_b"], arguments["object_start"], arguments["object_end"])

                # Add category axioms if requested
                if arguments.get("with_category_axioms", True):
                    cat_axioms = helpers.category_axioms()
                    premises = cat_axioms + premises

                result = {"premises": premises, "conclusion": conclusion, "note": "Use the 'prove' tool with these premises and conclusion to verify commutativity"}
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get-category-axioms":
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
                    axioms = helpers.natural_transformation_condition(functor_f, functor_g, component)
                elif concept == "monoid":
                    from mcp_logic.categorical_helpers import monoid_axioms

                    axioms = monoid_axioms()
                elif concept == "group":
                    from mcp_logic.categorical_helpers import group_axioms

                    axioms = group_axioms()
                else:
                    axioms = []

                result = {"concept": concept, "axioms": axioms}
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            else:
                raise ValueError(f"Unknown tool: {name}")

        except Exception as e:
            logger.error(f"Tool error: {e}", exc_info=True)
            return [types.TextContent(type="text", text=json.dumps({"error": str(e), "type": type(e).__name__}))]

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
    parser = argparse.ArgumentParser(description="MCP Logic Server")
    parser.add_argument("--prover-path", type=str, required=True, help="Path to Prover9/Mace4 binaries")
    args = parser.parse_args()
    asyncio.run(main(args.prover_path))


if __name__ == "__main__":
    cli()
