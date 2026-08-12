"""Tests for the Z3-backed arithmetic tools.

These cover the gap Prover9 cannot reach: reasoning about numbers.
"""

from __future__ import annotations

import pytest

from mcp_logic.smt_solver import (
    build_declarations,
    check_entailment,
    check_satisfiable,
    z3_available,
)


def test_z3_is_installed() -> None:
    """z3-solver is a required dependency, so absence is a failure.

    This used to be a module-level ``skipif``. When a bare ``uv sync``
    pruned the optional extras, 15 tests turned from passing to skipped and
    the suite still reported success — while prove_arithmetic and
    check_satisfiable were dead. A missing required dependency is a broken
    install, and the suite should say so.
    """
    assert z3_available(), (
        "z3-solver is missing. It is a required dependency — reinstall with "
        "`uv sync` (add --extra advisor if you also want the onboard LLM)."
    )


class TestDeclarations:
    """Declaration rendering, including the rejections."""

    def test_constants(self) -> None:
        out = build_declarations({"x": "Int", "b": "Bool"})
        assert "(declare-const x Int)" in out
        assert "(declare-const b Bool)" in out

    def test_uninterpreted_function(self) -> None:
        out = build_declarations({}, {"succ": ["Int", "Int"]})
        assert out == "(declare-fun succ (Int) Int)"

    def test_multi_argument_function(self) -> None:
        out = build_declarations({}, {"add": ["Int", "Int", "Int"]})
        assert out == "(declare-fun add (Int Int) Int)"

    def test_bad_sort_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsupported sort"):
            build_declarations({"x": "Integer"})

    def test_bad_function_sort_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsupported sort"):
            build_declarations({}, {"f": ["Nat", "Int"]})


class TestEntailment:
    """The verdict that matters: does it follow?"""

    def test_valid_arithmetic_entailment(self) -> None:
        result = check_entailment(
            ["(> x 0)", "(= y (+ x 1))"], "(> y 1)", {"x": "Int", "y": "Int"}
        )
        assert result["result"] == "proved"

    def test_invalid_entailment_returns_counterexample(self) -> None:
        result = check_entailment(["(> x 0)"], "(> x 5)", {"x": "Int"})
        assert result["result"] == "counterexample"
        # A concrete witness, not a vague "could not prove".
        assert int(result["counterexample"]["x"]) <= 5

    def test_the_case_prover9_cannot_do(self) -> None:
        # Prover9 has no arithmetic, so this is unreachable for it.
        result = check_entailment(["(> n 0)"], "(> (* 2 n) n)", {"n": "Int"})
        assert result["result"] == "proved"

    def test_real_arithmetic(self) -> None:
        result = check_entailment(["(> x 0.0)"], "(> (* x x) 0.0)", {"x": "Real"})
        assert result["result"] == "proved"

    def test_syntax_error_is_reported_not_raised(self) -> None:
        result = check_entailment(["(this is not smtlib"], "(> x 0)", {"x": "Int"})
        assert result["result"] == "error"
        assert "hint" in result

    def test_undeclared_variable_is_an_error(self) -> None:
        result = check_entailment(["(> undeclared 0)"], "(> undeclared 1)", {})
        assert result["result"] == "error"


class TestSatisfiability:
    """Consistency checking with a concrete witness."""

    def test_satisfiable_with_model(self) -> None:
        result = check_satisfiable(
            ["(> x 0)", "(< x 10)", "(= (mod x 3) 0)"], {"x": "Int"}
        )
        assert result["result"] == "satisfiable"
        value = int(result["model"]["x"])
        assert 0 < value < 10
        assert value % 3 == 0

    def test_contradiction_is_unsatisfiable(self) -> None:
        result = check_satisfiable(["(> x 5)", "(< x 3)"], {"x": "Int"})
        assert result["result"] == "unsatisfiable"

    def test_uninterpreted_function_constraint(self) -> None:
        # Every element has a successor distinct from itself — the question
        # that failed against Prover9 all afternoon.
        result = check_satisfiable(
            ["(forall ((x Int)) (not (= (succ x) x)))"],
            {},
            {"succ": ["Int", "Int"]},
        )
        assert result["result"] == "satisfiable"

    def test_bad_sort_reported_as_error(self) -> None:
        result = check_satisfiable(["(> x 0)"], {"x": "Integer"})
        assert result["result"] == "error"
