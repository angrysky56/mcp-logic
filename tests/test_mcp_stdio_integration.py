"""End-to-end MCP stdio coverage against the bundled LADR executables."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent


def _json_result(result: object) -> dict[str, object]:
    content = getattr(result, "content", None)
    assert isinstance(content, list) and content
    assert isinstance(content[0], TextContent)
    payload = json.loads(content[0].text)
    assert isinstance(payload, dict)
    return payload


@pytest.mark.asyncio
async def test_stdio_server_runs_prover9_and_mace4_through_mcp(
    prover_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parent.parent
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "mcp_logic.server",
            "--prover-path",
            str(prover_path),
            "--no-advisor",
        ],
        cwd=project_root,
    )

    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            listed = await session.list_tools()
            tool_names = {tool.name for tool in listed.tools}
            assert {"prove", "find_model"} <= tool_names

            proof = await session.call_tool(
                "prove",
                {
                    "premises": [
                        "all x (human(x) -> mortal(x))",
                        "human(socrates)",
                    ],
                    "conclusion": "mortal(socrates)",
                },
            )
            assert proof.isError is False
            assert _json_result(proof)["result"] == "proved"

            model = await session.call_tool(
                "find_model",
                {
                    "premises": ["human(socrates)"],
                    "domain_size": 2,
                },
            )
            assert model.isError is False
            assert _json_result(model)["result"] == "model_found"
