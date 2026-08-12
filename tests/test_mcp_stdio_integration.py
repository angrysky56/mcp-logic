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
            assert proof.is_error is False
            assert _json_result(proof)["result"] == "proved"

            model = await session.call_tool(
                "find_model",
                {
                    "premises": ["human(socrates)"],
                    "domain_size": 2,
                },
            )
            assert model.is_error is False
            assert _json_result(model)["result"] == "model_found"

            counterexample = await session.call_tool(
                "find_counterexample",
                {
                    "premises": ["p(a)"],
                    "conclusion": "q(a)",
                },
            )
            assert counterexample.is_error is False
            counterexample_payload = _json_result(counterexample)
            assert counterexample_payload["result"] == "model_found"
            assert counterexample_payload["decided"] is True
            assert counterexample_payload["fragment"] == "bsr"
            assert counterexample_payload["model_bound"] == 1

            contradiction = await session.call_tool(
                "find_model",
                {"premises": ["p(a)", "-p(a)"]},
            )
            assert contradiction.is_error is False
            contradiction_payload = _json_result(contradiction)
            assert contradiction_payload["result"] == "no_model_found"
            assert contradiction_payload["decided"] is True
            assert contradiction_payload["fragment"] == "bsr"
            assert "No model exists" in contradiction_payload["reason"]

            valid_argument = await session.call_tool(
                "find_counterexample",
                {"premises": ["p(a)"], "conclusion": "p(a)"},
            )
            assert valid_argument.is_error is False
            valid_payload = _json_result(valid_argument)
            assert valid_payload["result"] == "no_model_found"
            assert valid_payload["decided"] is True
            assert valid_payload["interpretation"].startswith(
                "No counterexample exists."
            )
            assert "may" not in valid_payload["interpretation"].lower()

            non_entailment = await session.call_tool(
                "find_counterexample",
                {
                    "premises": ["exists x exists y (x != y)"],
                    "conclusion": "p(a)",
                },
            )
            assert non_entailment.is_error is False
            non_entailment_payload = _json_result(non_entailment)
            assert non_entailment_payload["result"] == "model_found"
            assert non_entailment_payload["decided"] is True
            assert non_entailment_payload["fragment"] == "bsr"
            assert non_entailment_payload["model"]["domain_size"] >= 2

            monadic_model = await session.call_tool(
                "find_model",
                {"premises": ["all x exists y (x != y)"]},
            )
            assert monadic_model.is_error is False
            monadic_payload = _json_result(monadic_model)
            assert monadic_payload["result"] == "model_found"
            assert monadic_payload["decided"] is True
            assert monadic_payload["fragment"] == "monadic"
            assert monadic_payload["model_bound"] == 2
            assert monadic_payload["model"]["domain_size"] == 2

            impossible_monadic = await session.call_tool(
                "find_model",
                {
                    "premises": [
                        "all x exists y (x != y)",
                        "all x all y (x = y)",
                    ]
                },
            )
            assert impossible_monadic.is_error is False
            impossible_payload = _json_result(impossible_monadic)
            assert impossible_payload["result"] == "no_model_found"
            assert impossible_payload["decided"] is True
            assert impossible_payload["fragment"] == "monadic"
            assert "No model exists" in impossible_payload["reason"]

            # Error cases & parameter validation
            missing_conclusion = await session.call_tool(
                "prove",
                {"premises": ["p"]},
            )
            assert missing_conclusion.is_error is True
            missing_payload = _json_result(missing_conclusion)
            assert "error" in missing_payload

            syntax_err = await session.call_tool(
                "prove",
                {"premises": ["(p &"], "conclusion": "q"},
            )
            assert syntax_err.is_error is False
            syntax_payload = _json_result(syntax_err)
            assert syntax_payload["result"] == "syntax_error"

            # check_well_formed
            cwf = await session.call_tool(
                "check_well_formed",
                {"statements": ["p -> q", "all x (man(x))"]},
            )
            assert cwf.is_error is False
            cwf_payload = _json_result(cwf)
            assert cwf_payload["valid"] is True

            # check_contingency
            contingency = await session.call_tool(
                "check_contingency",
                {"formula": "p & q"},
            )
            assert contingency.is_error is False
            contingency_payload = _json_result(contingency)
            assert contingency_payload["is_contingent"] is True

            # verify_commutativity
            comm = await session.call_tool(
                "verify_commutativity",
                {
                    "path_a": ["f", "g"],
                    "path_b": ["h"],
                    "object_start": "A",
                    "object_end": "C",
                    "with_category_axioms": True,
                },
            )
            assert comm.is_error is False
            comm_payload = _json_result(comm)
            assert "conclusion" in comm_payload

            # get_category_axioms
            axioms = await session.call_tool(
                "get_category_axioms",
                {"concept": "group"},
            )
            assert axioms.is_error is False
            axioms_payload = _json_result(axioms)
            assert len(axioms_payload["axioms"]) > 0

            # abductive_explain (propositional)
            abd = await session.call_tool(
                "abductive_explain",
                {
                    "observation": "wet_grass",
                    "candidates": ["rained", "sprinkler"],
                    "background": ["rained -> wet_grass", "sprinkler -> wet_grass"],
                },
            )
            assert abd.is_error is False
            abd_payload = _json_result(abd)
            assert abd_payload["best_explanation"] in {"rained", "sprinkler"}

            # unknown tool
            unknown = await session.call_tool(
                "non_existent_tool",
                {},
            )
            assert unknown.is_error is True
            unknown_payload = _json_result(unknown)
            assert "error" in unknown_payload
