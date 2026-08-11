"""Tests for the LogicAdvisor agentic solver.

Two modes:
- **Unit tests** (default): Mock the LLM and solver, verifying the 3-phase
  pipeline logic, plan parsing, error handling, and disabled-mode behavior.
- **Integration tests** (``-m integration``): Require a real GGUF model and
  GPU.  Skipped in CI.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_logic.logic_advisor import (
    AdvisorDisabledError,
    AdvisorResult,
    LogicAdvisor,
    _strip_think_blocks,
)


# ── Fixtures ────────────────────────────────────────────────────────────


class FakeSolver:
    """In-memory solver that records calls and returns canned responses."""

    def __init__(self) -> None:
        self.prove_calls: list[dict[str, Any]] = []
        self.find_model_calls: list[dict[str, Any]] = []
        self.find_counterexample_calls: list[dict[str, Any]] = []
        self.check_well_formed_calls: list[dict[str, Any]] = []
        self.check_contingency_calls: list[dict[str, Any]] = []

        # Default canned responses.
        self.prove_result: dict[str, Any] = {
            "result": "proved",
            "proof": "1 human(socrates). [assumption]\n2 mortal(socrates). [resolution 1,3]",
            "stats": {"length": 5, "seconds": 0.01},
        }
        self.find_model_result: dict[str, Any] = {
            "result": "model_found",
            "domain_size": 2,
            "model": {"p": [[True, False]], "q": [[False, True]]},
        }
        self.find_counterexample_result: dict[str, Any] = {
            "result": "model_found",
            "domain_size": 2,
        }
        self.check_contingency_result: dict[str, Any] = {
            "formula": "p -> p",
            "is_tautology": True,
            "is_contingent": False,
            "is_contradiction": False,
            "message": "Tautology",
        }

    async def prove(
        self, premises: list[str], conclusion: str, *, timeout: int = 60
    ) -> dict[str, Any]:
        self.prove_calls.append(
            {"premises": premises, "conclusion": conclusion, "timeout": timeout}
        )
        return self.prove_result

    async def find_model(
        self,
        premises: list[str],
        *,
        domain_size: int | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        self.find_model_calls.append(
            {"premises": premises, "domain_size": domain_size, "timeout": timeout}
        )
        return self.find_model_result

    async def find_counterexample(
        self,
        premises: list[str],
        conclusion: str,
        *,
        domain_size: int | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        self.find_counterexample_calls.append(
            {
                "premises": premises,
                "conclusion": conclusion,
                "domain_size": domain_size,
                "timeout": timeout,
            }
        )
        return self.find_counterexample_result

    async def check_well_formed(self, statements: list[str]) -> dict[str, Any]:
        self.check_well_formed_calls.append({"statements": statements})
        return {"valid": True}

    async def check_contingency(self, formula: str) -> dict[str, Any]:
        self.check_contingency_calls.append({"formula": formula})
        return self.check_contingency_result


@pytest.fixture
def fake_solver() -> FakeSolver:
    return FakeSolver()


def _make_advisor(
    solver: FakeSolver,
    *,
    enabled: bool = True,
) -> LogicAdvisor:
    """Create a LogicAdvisor with the LLM mocked out."""
    return LogicAdvisor(
        solver=solver,
        model_path="/fake/model.gguf",
        enabled=enabled,
    )


def _mock_llm_responses(advisor: LogicAdvisor, responses: list[str]) -> None:
    """Patch the advisor's LLM calls to return canned responses in order."""
    call_count = {"n": 0}
    original_responses = list(responses)

    async def fake_llm_call(system: str, user: str, max_tokens: int = 2048) -> str:
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(original_responses):
            return original_responses[idx]
        return '{"tool": "none", "reason": "no more canned responses"}'

    advisor._llm_call = fake_llm_call  # type: ignore[assignment]
    # Also skip the model loading.
    advisor._model = MagicMock()


# ── Unit Tests ──────────────────────────────────────────────────────────


class TestStripThinkBlocks:
    """Test the <think> block stripping utility."""

    def test_strips_single_block(self) -> None:
        text = "<think>internal reasoning here</think>The answer is 42."
        assert _strip_think_blocks(text) == "The answer is 42."

    def test_strips_multiline_block(self) -> None:
        text = "<think>\nstep 1\nstep 2\n</think>\nFinal answer."
        assert _strip_think_blocks(text) == "Final answer."

    def test_strips_multiple_blocks(self) -> None:
        text = "<think>a</think>Hello <think>b</think>world"
        assert _strip_think_blocks(text) == "Hello world"

    def test_no_think_blocks(self) -> None:
        text = "Just a normal response."
        assert _strip_think_blocks(text) == "Just a normal response."

    def test_empty_string(self) -> None:
        assert _strip_think_blocks("") == ""


class TestPlanParsing:
    """Test JSON plan extraction from LLM output."""

    def test_clean_json(self) -> None:
        plan = LogicAdvisor._parse_plan(
            '{"tool": "prove", "premises": ["p"], "conclusion": "p"}'
        )
        assert plan["tool"] == "prove"
        assert plan["premises"] == ["p"]

    def test_json_in_code_fence(self) -> None:
        text = '```json\n{"tool": "find_model", "premises": ["p & q"]}\n```'
        plan = LogicAdvisor._parse_plan(text)
        assert plan["tool"] == "find_model"

    def test_json_embedded_in_text(self) -> None:
        text = 'Here is the plan: {"tool": "check_contingency", "formula": "p -> p"}'
        plan = LogicAdvisor._parse_plan(text)
        assert plan["tool"] == "check_contingency"

    def test_garbage_falls_back(self) -> None:
        plan = LogicAdvisor._parse_plan("this is not json at all")
        assert plan["tool"] == "none"
        assert "reason" in plan


class TestAdvisorDisabled:
    """Test behavior when the advisor is disabled."""

    @pytest.mark.asyncio
    async def test_solve_raises_when_disabled(self, fake_solver: FakeSolver) -> None:
        advisor = _make_advisor(fake_solver, enabled=False)
        with pytest.raises(AdvisorDisabledError):
            await advisor.solve("any question")

    @pytest.mark.asyncio
    async def test_query_raises_when_disabled(self, fake_solver: FakeSolver) -> None:
        advisor = _make_advisor(fake_solver, enabled=False)
        with pytest.raises(AdvisorDisabledError):
            await advisor.query("any question")

    def test_enabled_property(self, fake_solver: FakeSolver) -> None:
        advisor = _make_advisor(fake_solver, enabled=False)
        assert advisor.enabled is False

    def test_loaded_property_initially_false(self, fake_solver: FakeSolver) -> None:
        advisor = _make_advisor(fake_solver, enabled=True)
        assert advisor.loaded is False


class TestSolvePipeline:
    """Test the 3-phase formalize → execute → interpret pipeline."""

    @pytest.mark.asyncio
    async def test_prove_pipeline(self, fake_solver: FakeSolver) -> None:
        """Full pipeline: formalize → prove → interpret."""
        advisor = _make_advisor(fake_solver)

        # Phase 1 returns a prove plan, Phase 3 returns an interpretation.
        _mock_llm_responses(advisor, [
            json.dumps({
                "tool": "prove",
                "premises": ["all x (human(x) -> mortal(x))", "human(socrates)"],
                "conclusion": "mortal(socrates)",
            }),
            "Yes, Socrates is mortal. The proof follows from the universal premise.",
        ])

        result = await advisor.solve(
            "If all humans are mortal and Socrates is human, is Socrates mortal?"
        )

        assert isinstance(result, AdvisorResult)
        assert "Socrates is mortal" in result.answer
        assert result.formalization["tool"] == "prove"
        assert result.solver_output["result"] == "proved"
        assert len(fake_solver.prove_calls) == 1
        assert fake_solver.prove_calls[0]["conclusion"] == "mortal(socrates)"

    @pytest.mark.asyncio
    async def test_find_model_pipeline(self, fake_solver: FakeSolver) -> None:
        advisor = _make_advisor(fake_solver)

        _mock_llm_responses(advisor, [
            json.dumps({
                "tool": "find_model",
                "premises": ["exists x exists y (x != y)"],
                "domain_size": 3,
            }),
            "A model was found with 2 elements where distinct elements exist.",
        ])

        result = await advisor.solve(
            "Find a model where there exist at least two distinct elements."
        )

        assert result.formalization["tool"] == "find_model"
        assert result.solver_output["result"] == "model_found"
        assert len(fake_solver.find_model_calls) == 1

    @pytest.mark.asyncio
    async def test_check_contingency_pipeline(self, fake_solver: FakeSolver) -> None:
        advisor = _make_advisor(fake_solver)

        _mock_llm_responses(advisor, [
            json.dumps({
                "tool": "check_contingency",
                "formula": "p -> p",
            }),
            "Yes, p -> p is a tautology.",
        ])

        result = await advisor.solve("Is p implies p a tautology?")

        assert result.formalization["tool"] == "check_contingency"
        assert result.solver_output["is_tautology"] is True
        assert len(fake_solver.check_contingency_calls) == 1

    @pytest.mark.asyncio
    async def test_none_tool_no_solver_call(self, fake_solver: FakeSolver) -> None:
        """When LLM says the question isn't a logic problem, no solver runs."""
        advisor = _make_advisor(fake_solver)

        _mock_llm_responses(advisor, [
            json.dumps({
                "tool": "none",
                "reason": "This is a factual question, not a logic problem.",
            }),
        ])

        result = await advisor.solve("What is the capital of France?")

        assert "not a logic problem" in result.answer
        assert result.formalization["tool"] == "none"
        assert len(fake_solver.prove_calls) == 0

    @pytest.mark.asyncio
    async def test_context_passed_to_formalization(
        self, fake_solver: FakeSolver
    ) -> None:
        """Context is included in the formalization prompt."""
        advisor = _make_advisor(fake_solver)
        captured_user_msg: list[str] = []

        async def capture_llm(system: str, user: str, max_tokens: int = 2048) -> str:
            captured_user_msg.append(user)
            if len(captured_user_msg) == 1:
                return json.dumps({"tool": "none", "reason": "test"})
            return "test answer"

        advisor._model = MagicMock()
        advisor._llm_call = capture_llm  # type: ignore[assignment]

        await advisor.solve("Debug this", context="Previous error output here")

        assert "Previous error output here" in captured_user_msg[0]

    @pytest.mark.asyncio
    async def test_solver_error_handled_gracefully(
        self, fake_solver: FakeSolver
    ) -> None:
        """If the solver throws, the error is captured, not raised."""
        advisor = _make_advisor(fake_solver)

        # Make the solver throw.
        async def exploding_prove(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("prover9 binary not found")

        fake_solver.prove = exploding_prove  # type: ignore[assignment]

        _mock_llm_responses(advisor, [
            json.dumps({
                "tool": "prove",
                "premises": ["p"],
                "conclusion": "q",
            }),
            "The solver encountered an error.",
        ])

        result = await advisor.solve("Prove p implies q")

        assert "error" in result.solver_output
        assert "prover9 binary not found" in result.solver_output["error"]


class TestQueryShortcut:
    """Test the simple string-in/string-out query() method."""

    @pytest.mark.asyncio
    async def test_query_returns_answer_string(
        self, fake_solver: FakeSolver
    ) -> None:
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(advisor, [
            json.dumps({
                "tool": "prove",
                "premises": ["p"],
                "conclusion": "p",
            }),
            "Yes, p is trivially provable from p.",
        ])

        answer = await advisor.query("Can you prove p from p?")
        assert isinstance(answer, str)
        assert "provable" in answer
