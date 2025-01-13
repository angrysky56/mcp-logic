import logging
import os
import subprocess
import tempfile
import argparse
import asyncio
from typing import Any, List, Dict, Optional
from pathlib import Path
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('mcp_logic')

class LogicEngine:
    def __init__(self, prover_path: str):
        """Initialize connection to Prover9"""
        self.prover_path = Path(prover_path)
        self.prover_exe = self.prover_path / "prover9.exe"
        
        if not self.prover_exe.exists():
            raise FileNotFoundError(f"Prover9 not found at {self.prover_exe}")
        
        logger.debug(f"Initialized Logic Engine with Prover9 at {self.prover_exe}")

    def _create_input_file(self, premises: List[str], goal: str) -> Path:
        """Create a Prover9 input file"""
        content = [
            "formulas(assumptions).",
            *[p if p.endswith(".") else p + "." for p in premises],
            "end_of_list.",
            "",
            "formulas(goals).",
            goal if goal.endswith(".") else goal + ".",
            "end_of_list."
        ]
        
        input_content = '\n'.join(content)
        logger.debug(f"Created input file content:\n{input_content}")
        
        fd, path = tempfile.mkstemp(suffix='.in', text=True)
        with os.fdopen(fd, 'w') as f:
            f.write(input_content)
        return Path(path)

    def _run_prover(self, input_path: Path, timeout: int = 60) -> Dict[str, Any]:
        """Run Prover9 directly"""
        try:
            logger.debug(f"Running Prover9 with input file: {input_path}")
            
            # Set working directory to Prover9 directory
            cwd = str(self.prover_exe.parent)
            result = subprocess.run(
                [str(self.prover_exe), "-f", str(input_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd
            )
            
            logger.debug(f"Prover9 stdout:\n{result.stdout}")
            if result.stderr:
                logger.debug(f"Prover9 stderr:\n{result.stderr}")
            
            if "THEOREM PROVED" in result.stdout:
                proof = result.stdout.split("PROOF =")[1].split("====")[0].strip()
                return {
                    "result": "proved",
                    "proof": proof,
                    "complete_output": result.stdout
                }
            elif "SEARCH FAILED" in result.stdout:
                return {
                    "result": "unprovable",
                    "reason": "Proof search failed",
                    "complete_output": result.stdout
                }
            elif "Fatal error" in result.stderr:
                return {
                    "result": "error",
                    "reason": "Syntax error",
                    "error": result.stderr
                }
            else:
                return {
                    "result": "error",
                    "reason": "Unexpected output",
                    "output": result.stdout,
                    "error": result.stderr
                }
        except subprocess.TimeoutExpired:
            logger.error(f"Proof search timed out after {timeout} seconds")
            return {
                "result": "timeout",
                "reason": f"Proof search exceeded {timeout} seconds"
            }
        except Exception as e:
            logger.error(f"Prover error: {e}")
            return {
                "result": "error",
                "reason": str(e)
            }
        finally:
            try:
                input_path.unlink()  # Clean up temp file
            except:
                pass

async def main(prover_path: str):
    logger.info(f"Starting Logic MCP Server with Prover9 at: {prover_path}")

    engine = LogicEngine(prover_path)
    server = Server("logic-manager")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """List available tools"""
        return [
            types.Tool(
                name="prove",
                description="Prove a logical statement using Prover9",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "premises": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of logical premises"
                        },
                        "conclusion": {
                            "type": "string",
                            "description": "Statement to prove"
                        }
                    },
                    "required": ["premises", "conclusion"],
                },
            ),
            types.Tool(
                name="check-well-formed",
                description="Check if logical statements are well-formed",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "statements": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Logical statements to check"
                        }
                    },
                    "required": ["statements"],
                },
            )
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Handle tool execution requests"""
        try:
            if name == "prove":
                input_file = engine._create_input_file(
                    arguments["premises"],
                    arguments["conclusion"]
                )
                results = engine._run_prover(input_file)
                return [types.TextContent(type="text", text=str(results))]

            elif name == "check-well-formed":
                check_file = engine._create_input_file(
                    arguments["statements"],
                    "true"  # Dummy goal for syntax check
                )
                results = engine._run_prover(check_file, timeout=5)
                is_valid = "Fatal error" not in str(results.get("error", ""))
                return [types.TextContent(
                    type="text",
                    text=str({"valid": is_valid, "details": results})
                )]
            
            else:
                raise ValueError(f"Unknown tool: {name}")

        except Exception as e:
            logger.error(f"Tool error: {e}")
            return [types.TextContent(type="text", text=f"Error: {str(e)}")]

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        logger.info("Server running with stdio transport")
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="logic",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

def cli():
    parser = argparse.ArgumentParser(description='MCP Logic Server')
    parser.add_argument('--prover-path', type=str, required=True,
                      help='Path to Prover9/Mace4 binaries')
    args = parser.parse_args()
    asyncio.run(main(args.prover_path))

if __name__ == '__main__':
    cli()