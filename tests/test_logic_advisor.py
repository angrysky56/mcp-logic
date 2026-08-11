"""Tests for the LogicAdvisor agentic solver.

Two modes:
- **Unit tests** (default): Mock the LLM and solver, verifying the 3-phase
  pipeline logic, plan parsing, error handling, and disabled-mode behavior.
- **Integration tests** (``-m integration``): Require a real GGUF model and
  GPU.  Skipped in CI.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from mcp_logic.logic_advisor import (
    _DEFAULT_MAX_TOKENS,
    _DEFAULT_N_CTX,
    AdvisorDisabledError,
    AdvisorResult,
    LogicAdvisor,
    _strip_think_blocks,
    infer_tool,
    looks_arithmetic,
    normalize_plan,
    normalize_syntax,
    parse_formalization,
    parse_smt_formalization,
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
        self.prove_arithmetic_calls: list[dict[str, Any]] = []
        self.check_satisfiable_calls: list[dict[str, Any]] = []

        self.prove_arithmetic_result: dict[str, Any] = {
            "result": "proved",
            "reason": "The negated conclusion is unsatisfiable.",
        }
        self.check_satisfiable_result: dict[str, Any] = {
            "result": "satisfiable",
            "model": {"x": "3"},
        }

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
        return self.check_well_formed_result

    # Overridable so tests can simulate a validator rejection.
    check_well_formed_result: dict[str, Any] = {"valid": True}

    async def check_contingency(self, formula: str) -> dict[str, Any]:
        self.check_contingency_calls.append({"formula": formula})
        return self.check_contingency_result

    async def prove_arithmetic(
        self,
        premises: list[str],
        conclusion: str,
        variables: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.prove_arithmetic_calls.append(
            {
                "premises": premises,
                "conclusion": conclusion,
                "variables": variables,
            }
        )
        return self.prove_arithmetic_result

    async def check_satisfiable(
        self,
        constraints: list[str],
        variables: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.check_satisfiable_calls.append(
            {"constraints": constraints, "variables": variables}
        )
        return self.check_satisfiable_result


@pytest.fixture
def fake_solver() -> FakeSolver:
    return FakeSolver()


def _make_advisor(
    solver: FakeSolver,
    *,
    enabled: bool = True,
    cache_size: int = 0,
    idle_unload_seconds: float | None = None,
) -> LogicAdvisor:
    """Create a LogicAdvisor with the LLM mocked out.

    Caching and idle unloading are off by default so the existing pipeline
    tests exercise the real path every time; the tests that care about
    those features opt in.
    """
    return LogicAdvisor(
        solver=solver,
        model_path="/fake/model.gguf",
        enabled=enabled,
        cache_size=cache_size,
        idle_unload_seconds=idle_unload_seconds,
    )


def _mock_llm_responses(advisor: LogicAdvisor, responses: list[str]) -> None:
    """Patch the advisor's LLM calls to return canned responses in order.

    Responses are consumed in order: formalization first, then the
    interpretation, with any repair calls in between.
    """
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
        _mock_llm_responses(
            advisor,
            [
                json.dumps(
                    {
                        "tool": "prove",
                        "premises": [
                            "all x (human(x) -> mortal(x))",
                            "human(socrates)",
                        ],
                        "conclusion": "mortal(socrates)",
                    }
                ),
                "Yes, Socrates is mortal. The proof follows from the universal premise.",
            ],
        )

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

        _mock_llm_responses(
            advisor,
            [
                json.dumps(
                    {
                        "tool": "find_model",
                        "premises": ["exists x exists y (x != y)"],
                        "domain_size": 3,
                    }
                ),
                "A model was found with 2 elements where distinct elements exist.",
            ],
        )

        result = await advisor.solve(
            "Find a model where there exist at least two distinct elements."
        )

        assert result.formalization["tool"] == "find_model"
        assert result.solver_output["result"] == "model_found"
        assert len(fake_solver.find_model_calls) == 1

    @pytest.mark.asyncio
    async def test_check_contingency_pipeline(self, fake_solver: FakeSolver) -> None:
        advisor = _make_advisor(fake_solver)

        _mock_llm_responses(
            advisor,
            [
                json.dumps(
                    {
                        "tool": "check_contingency",
                        "formula": "p -> p",
                    }
                ),
                "Yes, p -> p is a tautology.",
            ],
        )

        result = await advisor.solve("Is p implies p a tautology?")

        assert result.formalization["tool"] == "check_contingency"
        assert result.solver_output["is_tautology"] is True
        assert len(fake_solver.check_contingency_calls) == 1

    @pytest.mark.asyncio
    async def test_none_tool_no_solver_call(self, fake_solver: FakeSolver) -> None:
        """When LLM says the question isn't a logic problem, no solver runs."""
        advisor = _make_advisor(fake_solver)

        _mock_llm_responses(
            advisor,
            [
                json.dumps(
                    {
                        "tool": "none",
                        "reason": "This is a factual question, not a logic problem.",
                    }
                ),
            ],
        )

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

        _mock_llm_responses(
            advisor,
            [
                json.dumps(
                    {
                        "tool": "prove",
                        "premises": ["p"],
                        "conclusion": "q",
                    }
                ),
                "The solver encountered an error.",
            ],
        )

        result = await advisor.solve("Prove p implies q")

        assert "error" in result.solver_output
        assert "prover9 binary not found" in result.solver_output["error"]


class TestQueryShortcut:
    """Test the simple string-in/string-out query() method."""

    @pytest.mark.asyncio
    async def test_query_returns_answer_string(self, fake_solver: FakeSolver) -> None:
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            [
                json.dumps(
                    {
                        "tool": "prove",
                        "premises": ["p"],
                        "conclusion": "p",
                    }
                ),
                "Yes, p is trivially provable from p.",
            ],
        )

        answer = await advisor.query("Can you prove p from p?")
        assert isinstance(answer, str)
        assert "provable" in answer


# ── Syntax normalization ────────────────────────────────────────────────


class TestNormalizeSyntax:
    """The model drifts into Unicode/other-dialect notation; we rewrite it."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("∀x (Cat(x) → Animal(x))", "all x (Cat(x) -> Animal(x))"),
            ("∃x (Animal(x) ∧ Dog(x))", "exists x (Animal(x) & Dog(x))"),
            ("p ∨ ¬p", "p | -p"),
            ("p <=> q", "p <-> q"),
            ("p => q", "p -> q"),
            ("p || q", "p | q"),
            ("p && q", "p & q"),
            ("~p", "-p"),
            ("forall x (p(x))", "all x (p(x))"),
            ("x ≠ y", "x != y"),
            ("mortal(socrates).", "mortal(socrates)"),
        ],
    )
    def test_rewrites(self, raw: str, expected: str) -> None:
        assert normalize_syntax(raw) == expected

    def test_leaves_valid_formulas_untouched(self) -> None:
        formula = "all x (human(x) -> mortal(x))"
        assert normalize_syntax(formula) == formula

    def test_normalize_plan_covers_all_formula_fields(self) -> None:
        plan = {
            "tool": "prove",
            "premises": ["∀x (p(x) → q(x))"],
            "conclusion": "∃x q(x)",
        }
        cleaned = normalize_plan(plan)
        assert cleaned["premises"] == ["all x (p(x) -> q(x))"]
        assert cleaned["conclusion"] == "exists x q(x)"
        # Original must not be mutated.
        assert plan["conclusion"] == "∃x q(x)"


# ── Verification honesty ────────────────────────────────────────────────


class TestUnverifiedResults:
    """A solver failure must never be dressed up as an answer."""

    @pytest.mark.asyncio
    async def test_solver_error_yields_unverified_result(
        self, fake_solver: FakeSolver
    ) -> None:
        fake_solver.prove_result = {
            "result": "error",
            "reason": "Syntax error or invalid input",
        }
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            [
                json.dumps({"tool": "prove", "premises": ["p"], "conclusion": "q"}),
                "Yes! Absolutely provable.",  # must NOT be used
            ],
        )

        result = await advisor.solve("Does q follow from p?")
        assert result.verified is False
        assert "Absolutely provable" not in result.answer
        assert "Syntax error" in result.answer

    @pytest.mark.asyncio
    async def test_successful_proof_is_verified(self, fake_solver: FakeSolver) -> None:
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            [
                json.dumps({"tool": "prove", "premises": ["p"], "conclusion": "p"}),
                "Yes, trivially.",
            ],
        )
        result = await advisor.solve("Does p follow from p?")
        assert result.verified is True
        assert result.answer == "Yes, trivially."

    @pytest.mark.asyncio
    async def test_unformalizable_question_is_unverified(
        self, fake_solver: FakeSolver
    ) -> None:
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            [json.dumps({"tool": "none", "reason": "not a logic problem"})],
        )
        result = await advisor.solve("What is your favourite colour?")
        assert result.verified is False


# ── Validate-and-repair loop ────────────────────────────────────────────


class TestRepairLoop:
    """A rejected formalization gets exactly one repair attempt."""

    @pytest.mark.asyncio
    async def test_invalid_plan_is_repaired_then_executed(
        self, fake_solver: FakeSolver
    ) -> None:
        rejections = {"n": 0}

        async def picky_check(statements: list[str]) -> dict[str, Any]:
            rejections["n"] += 1
            if rejections["n"] == 1:
                return {
                    "valid": False,
                    "formula_results": [
                        {
                            "formula": statements[0],
                            "valid": False,
                            "errors": ["unknown token"],
                        }
                    ],
                    "set_errors": [],
                }
            return {"valid": True}

        fake_solver.check_well_formed = picky_check  # type: ignore[assignment]
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            [
                json.dumps({"tool": "prove", "premises": ["bad!"], "conclusion": "q"}),
                json.dumps({"tool": "prove", "premises": ["p"], "conclusion": "q"}),
                "Yes, q follows.",
            ],
        )

        result = await advisor.solve("Does q follow?")
        assert result.verified is True
        assert result.formalization["premises"] == ["p"]
        assert fake_solver.prove_calls[0]["premises"] == ["p"]

    @pytest.mark.asyncio
    async def test_repair_failure_returns_unverified(
        self, fake_solver: FakeSolver
    ) -> None:
        async def always_reject(statements: list[str]) -> dict[str, Any]:
            return {
                "valid": False,
                "formula_results": [],
                "set_errors": ["arity conflict on p"],
            }

        fake_solver.check_well_formed = always_reject  # type: ignore[assignment]
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            [
                json.dumps({"tool": "prove", "premises": ["p(x)"], "conclusion": "p"}),
                json.dumps({"tool": "prove", "premises": ["p(x)"], "conclusion": "p"}),
            ],
        )

        result = await advisor.solve("Does p follow?")
        assert result.verified is False
        assert "arity conflict" in result.answer
        # The solver must never have been invoked with an invalid plan.
        assert fake_solver.prove_calls == []


class TestSolverErrorRepair:
    """Prover9 is the authoritative parser; its rejection triggers a repair."""

    @pytest.mark.asyncio
    async def test_solver_syntax_error_triggers_repair_and_retry(
        self, fake_solver: FakeSolver
    ) -> None:
        # The permissive validator waves the bad plan through; only the
        # solver catches it.
        attempts: list[list[str]] = []

        async def picky_prove(
            premises: list[str], conclusion: str, *, timeout: int = 60
        ) -> dict[str, Any]:
            attempts.append(premises)
            if premises == ["All cats are animals"]:
                return {
                    "result": "error",
                    "error": "Fatal error:  sread_term error",
                }
            return {"result": "unprovable", "reason": "search exhausted"}

        fake_solver.prove = picky_prove  # type: ignore[assignment]
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            [
                json.dumps(
                    {
                        "tool": "prove",
                        "premises": ["All cats are animals"],
                        "conclusion": "q",
                    }
                ),
                json.dumps(
                    {
                        "tool": "prove",
                        "premises": ["all x (cat(x) -> animal(x))"],
                        "conclusion": "q",
                    }
                ),
                "No, it does not follow.",
            ],
        )

        result = await advisor.solve("Does it follow?")
        assert len(attempts) == 2, "solver should have been retried after repair"
        assert attempts[1] == ["all x (cat(x) -> animal(x))"]
        assert result.verified is True
        assert result.answer == "No, it does not follow."

    @pytest.mark.asyncio
    async def test_repair_that_still_fails_stays_unverified(
        self, fake_solver: FakeSolver
    ) -> None:
        fake_solver.prove_result = {
            "result": "error",
            "error": "Fatal error:  sread_term error",
        }
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            [
                json.dumps({"tool": "prove", "premises": ["junk"], "conclusion": "q"}),
                json.dumps({"tool": "prove", "premises": ["junk2"], "conclusion": "q"}),
                "Sounds right to me!",  # must never surface
            ],
        )

        result = await advisor.solve("Does it follow?")
        assert result.verified is False
        assert "Sounds right" not in result.answer


class TestCounterexampleRouting:
    """An unprovable verdict should come with a concrete countermodel."""

    @pytest.mark.asyncio
    async def test_unprovable_triggers_countermodel_search(
        self, fake_solver: FakeSolver
    ) -> None:
        fake_solver.prove_result = {
            "result": "unprovable",
            "reason": "Proof search exhausted.",
        }
        fake_solver.find_counterexample_result = {
            "result": "model_found",
            "domain_size": 2,
            "model": {"cat": [True, False], "dog": [False, True]},
        }
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            [
                "PREMISE: all x (cat(x) -> animal(x))\n"
                "PREMISE: exists x (animal(x) & dog(x))\n"
                "GOAL: exists x (cat(x) & dog(x))",
                "No — here is a world where no cat is a dog.",
            ],
        )

        result = await advisor.solve("Does it follow that some cats are dogs?")

        assert len(fake_solver.find_counterexample_calls) == 1
        assert result.solver_output["countermodel"]["result"] == "model_found"
        # Unprovable is a genuine verdict, so this stays verified.
        assert result.verified is True

    @pytest.mark.asyncio
    async def test_proved_does_not_search_for_countermodel(
        self, fake_solver: FakeSolver
    ) -> None:
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            ["PREMISE: human(socrates)\nGOAL: mortal(socrates)", "Yes."],
        )
        await advisor.solve("Is Socrates mortal?")
        assert fake_solver.find_counterexample_calls == []

    @pytest.mark.asyncio
    async def test_failed_countermodel_search_is_not_fatal(
        self, fake_solver: FakeSolver
    ) -> None:
        fake_solver.prove_result = {"result": "unprovable", "reason": "exhausted"}
        fake_solver.find_counterexample_result = {"error": "Mace4 not available"}
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            ["PREMISE: p\nGOAL: q", "No, it does not follow."],
        )

        result = await advisor.solve("Does q follow from p?")
        assert "countermodel" not in result.solver_output
        assert result.verified is True


class TestAnswerCache:
    """Repeat questions must not re-run the GPU."""

    @pytest.mark.asyncio
    async def test_repeat_question_served_from_cache(
        self, fake_solver: FakeSolver
    ) -> None:
        advisor = _make_advisor(fake_solver, cache_size=8)
        _mock_llm_responses(
            advisor,
            ["PREMISE: human(socrates)\nGOAL: mortal(socrates)", "Yes."],
        )

        first = await advisor.solve("Is Socrates mortal?")
        second = await advisor.solve("Is Socrates mortal?")

        assert second.answer == first.answer
        assert "(served from cache)" in second.steps[-1]
        # The solver ran exactly once.
        assert len(fake_solver.prove_calls) == 1

    @pytest.mark.asyncio
    async def test_different_context_is_a_different_entry(
        self, fake_solver: FakeSolver
    ) -> None:
        advisor = _make_advisor(fake_solver, cache_size=8)
        _mock_llm_responses(
            advisor,
            [
                "PREMISE: p\nGOAL: q",
                "Yes.",
                "PREMISE: p\nGOAL: q",
                "Yes, given the context.",
            ],
        )

        await advisor.solve("Does q follow?")
        await advisor.solve("Does q follow?", context="assume p")
        assert len(fake_solver.prove_calls) == 2

    @pytest.mark.asyncio
    async def test_use_cache_false_forces_a_fresh_solve(
        self, fake_solver: FakeSolver
    ) -> None:
        advisor = _make_advisor(fake_solver, cache_size=8)
        _mock_llm_responses(
            advisor,
            ["PREMISE: p\nGOAL: q", "Yes.", "PREMISE: p\nGOAL: q", "Yes again."],
        )

        await advisor.solve("Does q follow?")
        await advisor.solve("Does q follow?", use_cache=False)
        assert len(fake_solver.prove_calls) == 2

    @pytest.mark.asyncio
    async def test_cache_evicts_least_recently_used(
        self, fake_solver: FakeSolver
    ) -> None:
        advisor = _make_advisor(fake_solver, cache_size=2)
        _mock_llm_responses(advisor, [])  # every call falls through to "none"

        await advisor.solve("q one")
        await advisor.solve("q two")
        await advisor.solve("q three")

        assert len(advisor._cache) == 2
        assert ("q one", "") not in advisor._cache

    @pytest.mark.asyncio
    async def test_clear_cache(self, fake_solver: FakeSolver) -> None:
        advisor = _make_advisor(fake_solver, cache_size=8)
        _mock_llm_responses(advisor, ["PREMISE: p\nGOAL: q", "Yes."])
        await advisor.solve("Does q follow?")
        advisor.clear_cache()
        assert len(advisor._cache) == 0


class TestIdleUnload:
    """VRAM should not stay pinned indefinitely."""

    @pytest.mark.asyncio
    async def test_model_released_after_idle_window(
        self, fake_solver: FakeSolver
    ) -> None:
        advisor = _make_advisor(fake_solver, idle_unload_seconds=0.05)
        _mock_llm_responses(advisor, ["PREMISE: p\nGOAL: q", "Yes."])

        await advisor.solve("Does q follow?")
        assert advisor.loaded is True

        await asyncio.sleep(0.15)
        assert advisor.loaded is False

    @pytest.mark.asyncio
    async def test_activity_postpones_the_unload(self, fake_solver: FakeSolver) -> None:
        advisor = _make_advisor(fake_solver, idle_unload_seconds=0.2)
        _mock_llm_responses(advisor, [])

        await advisor.solve("first")
        await asyncio.sleep(0.1)
        await advisor.solve("second", use_cache=False)
        await asyncio.sleep(0.1)
        # 0.2s total elapsed, but the timer restarted at 0.1s.
        assert advisor.loaded is True

    @pytest.mark.asyncio
    async def test_disabled_idle_unload_keeps_model(
        self, fake_solver: FakeSolver
    ) -> None:
        advisor = _make_advisor(fake_solver, idle_unload_seconds=None)
        _mock_llm_responses(advisor, ["PREMISE: p\nGOAL: q", "Yes."])
        await advisor.solve("Does q follow?")
        await asyncio.sleep(0.1)
        assert advisor.loaded is True

    @pytest.mark.asyncio
    async def test_unload_cancels_the_timer(self, fake_solver: FakeSolver) -> None:
        advisor = _make_advisor(fake_solver, idle_unload_seconds=10.0)
        _mock_llm_responses(advisor, ["PREMISE: p\nGOAL: q", "Yes."])
        await advisor.solve("Does q follow?")
        await advisor.unload()
        assert advisor._idle_task is None
        assert advisor.loaded is False


class TestArithmeticRouting:
    """Numeric questions must reach Z3, not Prover9."""

    @pytest.mark.parametrize(
        "question",
        [
            "If x is greater than 0, is 2x greater than x?",
            "Alice is at least 18. Is she at least 16?",
            "Is the sum of two even numbers even?",
            "Is there a number between 0 and 10 divisible by 3?",
        ],
    )
    def test_arithmetic_detected(self, question: str) -> None:
        assert looks_arithmetic(question) is True

    @pytest.mark.parametrize(
        "question",
        [
            "All humans are mortal. Socrates is a human. Is Socrates mortal?",
            "All cats are animals. Some animals are dogs. Do cats bark?",
            "Is p or not p a tautology?",
            "What is your favourite colour?",
            # Regression: quantifier phrasing that merely sounds numeric.
            "Find a model where there exist at least two distinct elements.",
            "Is there at most one largest element in this ordering?",
            "Every number-crunching machine is a machine. Is that valid?",
        ],
    )
    def test_non_arithmetic_stays_on_prover9(self, question: str) -> None:
        assert looks_arithmetic(question) is False

    def test_smt_lines_become_entailment_plan(self) -> None:
        raw = "VAR: x Int\nPREMISE: (> x 0)\nGOAL: (> (* 2 x) x)"
        plan = parse_smt_formalization(raw)
        assert plan["tool"] == "prove_arithmetic"
        assert plan["variables"] == {"x": "Int"}
        assert plan["conclusion"] == "(> (* 2 x) x)"

    def test_smt_lines_without_goal_become_satisfiability(self) -> None:
        raw = "VAR: n Int\nPREMISE: (> n 0)\nPREMISE: (< n 10)"
        plan = parse_smt_formalization(raw)
        assert plan["tool"] == "check_satisfiable"
        assert len(plan["constraints"]) == 2

    def test_smt_garbage_is_none(self) -> None:
        assert parse_smt_formalization("NONE")["tool"] == "none"

    def test_missing_var_lines_are_recovered(self) -> None:
        # The model routinely omits VAR: lines; Z3 would reject the script.
        plan = parse_smt_formalization("PREMISE: (> x 0)\nGOAL: (> (* 2 x) x)")
        assert plan["variables"] == {"x": "Int"}

    def test_declared_sorts_win_over_inference(self) -> None:
        plan = parse_smt_formalization("VAR: x Real\nPREMISE: (> x 0)\nGOAL: (> x -1)")
        assert plan["variables"]["x"] == "Real"

    def test_decimal_literals_infer_real(self) -> None:
        plan = parse_smt_formalization("PREMISE: (> price 0.5)")
        assert plan["variables"]["price"] == "Real"

    def test_operators_are_not_mistaken_for_variables(self) -> None:
        plan = parse_smt_formalization("PREMISE: (and (> n 0) (not (= (mod n 3) 1)))")
        assert set(plan["variables"]) == {"n"}

    @pytest.mark.asyncio
    async def test_pipeline_routes_arithmetic_to_z3(
        self, fake_solver: FakeSolver
    ) -> None:
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            [
                "VAR: x Int\nPREMISE: (> x 0)\nGOAL: (> (* 2 x) x)",
                "Yes, doubling a positive number always makes it larger.",
            ],
        )

        result = await advisor.solve("If x is greater than 0, is 2x greater than x?")

        assert result.verified is True
        assert len(fake_solver.prove_arithmetic_calls) == 1
        # Prover9 must not have been handed an arithmetic question.
        assert fake_solver.prove_calls == []

    @pytest.mark.asyncio
    async def test_smt_syntax_is_not_mangled_by_prover9_rewrites(
        self, fake_solver: FakeSolver
    ) -> None:
        # `=>` is SMT-LIB implication; the Prover9 normalizer rewrites it
        # to `->`, which Z3 does not understand.
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            [
                "VAR: x Int\nPREMISE: (=> (> x 0) (>= x 1))\nGOAL: (>= x 0)",
                "Yes.",
            ],
        )

        await advisor.solve("If x > 0 then is x >= 0?")
        assert fake_solver.prove_arithmetic_calls[0]["premises"] == [
            "(=> (> x 0) (>= x 1))"
        ]

    @pytest.mark.asyncio
    async def test_z3_unknown_is_reported_unverified(
        self, fake_solver: FakeSolver
    ) -> None:
        fake_solver.prove_arithmetic_result = {
            "result": "unknown",
            "reason": "Z3 could not decide (incomplete quantifiers).",
        }
        advisor = _make_advisor(fake_solver)
        _mock_llm_responses(
            advisor,
            [
                "VAR: x Int\nPREMISE: (> x 0)\nGOAL: (> (* x x x) 0)",
                "Sure, definitely true!",  # must not surface
            ],
        )

        result = await advisor.solve("Is x cubed positive when x is above 0?")
        assert result.verified is False
        assert "Sure, definitely" not in result.answer
        assert "could not decide" in result.answer


class TestUnterminatedThinkBlock:
    """A <think> block the model never closed must not eat the answer."""

    def test_unterminated_think_keeps_content(self) -> None:
        text = '<think>reasoning here\n{"tool": "prove"}'
        out = _strip_think_blocks(text)
        assert "<think>" not in out
        assert '{"tool": "prove"}' in out

    def test_closed_block_still_removed_entirely(self) -> None:
        text = '<think>hidden</think>\n{"tool": "prove"}'
        assert "hidden" not in _strip_think_blocks(text)

    def test_plan_recovered_from_unterminated_think(self) -> None:
        # The exact shape observed from TwIL-LM3: opens <think>, never closes,
        # sketches an example object, then states the real plan last.
        raw = (
            "<think>The user asks about Socrates. Format is like "
            '{"tool": "x", "premises": []} and so on.\n\n'
            "The JSON output should be:\n"
            '{"tool": "prove", "premises": ["all x (human(x) -> mortal(x))", '
            '"human(socrates)"], "conclusion": "mortal(socrates)"}'
        )
        plan = LogicAdvisor._parse_plan(_strip_think_blocks(raw))
        assert plan["tool"] == "prove"
        assert plan["conclusion"] == "mortal(socrates)"
        assert len(plan["premises"]) == 2

    def test_last_object_wins_over_greedy_span(self) -> None:
        raw = 'Consider {"tool": "find_model"} then finally {"tool": "prove"}'
        assert LogicAdvisor._parse_plan(raw)["tool"] == "prove"

    def test_braces_inside_strings_do_not_confuse_scanner(self) -> None:
        raw = '{"tool": "prove", "conclusion": "p(\\"{\\") & q"}'
        assert LogicAdvisor._parse_plan(raw)["tool"] == "prove"


class TestDecodingSettings:
    """Model-card decoding settings must actually reach llama.cpp."""

    def test_repeat_penalty_pinned_to_one(self, fake_solver: FakeSolver) -> None:
        captured: dict[str, Any] = {}

        class FakeModel:
            def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
                captured.update(kwargs)
                return {"choices": [{"message": {"content": "{}"}}]}

        advisor = _make_advisor(fake_solver)
        advisor._model = FakeModel()
        advisor._create_chat_completion([], 2048, 0.0)

        # llama.cpp defaults this to 1.1; the card calls 1.0 load-bearing.
        assert captured["repeat_penalty"] == 1.0

    def test_generation_budget_meets_model_card_minimum(self) -> None:
        # The card: a short budget truncates the <think> block and "costs far
        # more accuracy than the quantization does".
        assert _DEFAULT_MAX_TOKENS >= 2048
        assert _DEFAULT_N_CTX >= 8192


class TestToolInference:
    """Tool choice is derived from the translation, not a second LLM call."""

    def test_goal_means_prove(self) -> None:
        parts = {"premises": ["human(socrates)"], "goal": "mortal(socrates)"}
        assert infer_tool("Does it follow that Socrates is mortal?", parts) == "prove"

    def test_bare_formula_means_contingency(self) -> None:
        assert infer_tool("Is p or not p a tautology?", {"formula": "p | -p"}) == (
            "check_contingency"
        )

    def test_premises_only_means_find_model(self) -> None:
        parts = {"premises": ["exists x exists y (x != y)"]}
        assert infer_tool("Find a world with two things.", parts) == "find_model"

    def test_explicit_counterexample_request_overrides_prove(self) -> None:
        parts = {"premises": ["p"], "goal": "q"}
        assert infer_tool("Find a counterexample to q.", parts) == (
            "find_counterexample"
        )
        assert infer_tool("Can you disprove q?", parts) == "find_counterexample"

    def test_nothing_translated_means_none(self) -> None:
        assert infer_tool("What is your favourite colour?", {}) == "none"

    def test_consistency_question_routes_to_model_finding(self) -> None:
        parts = {"premises": ["p", "-p"]}
        assert infer_tool("Are these axioms consistent?", parts) == "find_model"


class TestLineFormalization:
    """Labelled-line output is the format this model handles best."""

    def test_prove_plan(self) -> None:
        raw = (
            "PREMISE: all x (cat(x) -> animal(x))\n"
            "PREMISE: exists x (animal(x) & dog(x))\n"
            "GOAL: exists x (cat(x) & dog(x))"
        )
        plan = parse_formalization(raw, question="Does it follow?")
        assert plan["tool"] == "prove"
        assert len(plan["premises"]) == 2
        assert plan["conclusion"] == "exists x (cat(x) & dog(x))"

    def test_contingency_plan(self) -> None:
        plan = parse_formalization("FORMULA: p | -p", question="Is it a tautology?")
        assert plan == {"tool": "check_contingency", "formula": "p | -p"}

    def test_find_model_with_domain(self) -> None:
        raw = "PREMISE: exists x exists y (x != y)\nDOMAIN: 3"
        plan = parse_formalization(raw, question="Find a model with two things.")
        assert plan["domain_size"] == 3
        assert "conclusion" not in plan

    def test_lines_survive_surrounding_reasoning(self) -> None:
        raw = (
            "<think>I should translate this carefully.</think>\n"
            "Here is the translation:\n"
            "PREMISE: human(socrates)\n"
            "GOAL: mortal(socrates)\n"
            "That should do it."
        )
        plan = parse_formalization(raw, question="Is Socrates mortal?")
        assert plan["premises"] == ["human(socrates)"]
        assert plan["conclusion"] == "mortal(socrates)"

    def test_prove_without_goal_is_rejected(self) -> None:
        plan = parse_formalization(
            "PREMISE: p", question="Does q follow?", tool="prove"
        )
        assert plan["tool"] == "none"

    def test_falls_back_to_json_shape(self) -> None:
        # The model sometimes answers in the old JSON format anyway.
        raw = '{"tool": "prove", "premises": ["p"], "conclusion": "q"}'
        plan = parse_formalization(raw, "prove")
        assert plan["conclusion"] == "q"

    def test_unusable_output_reports_none(self) -> None:
        plan = parse_formalization("I am not sure what you mean.", question="huh?")
        assert plan["tool"] == "none"
        assert "reason" in plan
