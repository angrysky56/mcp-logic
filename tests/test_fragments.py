"""Decidable-fragment classification and bounded model-search tests."""

from pathlib import Path

import pytest

from mcp_logic.fragments import classify_counterexample, classify_fragment
from mcp_logic.mace4_wrapper import Mace4Wrapper


def test_bsr_formula_has_a_computable_model_bound() -> None:
    verdict = classify_fragment(["exists x all y (p(x) -> p(y))"])

    assert verdict.fragment == "bsr"
    assert verdict.decidable is True
    assert verdict.model_bound == 1


def test_bsr_bound_counts_existential_witnesses_and_constants() -> None:
    verdict = classify_fragment(["exists x (p(x, a))"])

    assert verdict.fragment == "bsr"
    assert verdict.model_bound == 2


def test_classifier_accepts_ladr_trailing_periods() -> None:
    verdict = classify_fragment(["exists x (p(x))."])

    assert verdict.fragment == "bsr"
    assert verdict.decidable is True


def test_counterexample_classifier_normalizes_goal_before_negating_it() -> None:
    verdict = classify_counterexample(["p(a)."], "q(a).")

    assert verdict.fragment == "bsr"
    assert verdict.decidable is True


def test_positive_arity_function_is_not_bsr() -> None:
    verdict = classify_fragment(["all x (p(f(x)))"])

    assert verdict.fragment == "unknown"
    assert verdict.decidable is False
    assert verdict.model_bound is None


def test_monadic_formula_gets_unary_type_bound() -> None:
    verdict = classify_fragment(["all x exists y (p(x) -> p(y))"])

    assert verdict.fragment == "monadic"
    assert verdict.decidable is True
    assert verdict.model_bound == 2


def test_monadic_equality_bound_preserves_distinct_same_type_elements() -> None:
    verdict = classify_fragment(["all x exists y (x != y)"])

    assert verdict.fragment == "monadic"
    assert verdict.decidable is True
    assert verdict.model_bound == 2


def test_monadic_bound_over_cap_is_not_operationally_decidable() -> None:
    predicates = " & ".join(f"p{i}(x)" for i in range(11))
    verdict = classify_fragment([f"all x exists y (({predicates}) -> p0(y))"])

    assert verdict.fragment == "monadic"
    assert verdict.decidable is False
    assert verdict.model_bound is None
    assert "exceeds" in verdict.reason


def test_dense_strict_order_is_the_negative_control() -> None:
    verdict = classify_fragment(
        [
            "all x exists y (lt(x,y))",
            "all x (-lt(x,x))",
            "all x all y all z ((lt(x,y) & lt(y,z)) -> lt(x,z))",
            "all x all y (lt(x,y) -> exists z (lt(x,z) & lt(z,y)))",
        ]
    )

    assert verdict.fragment == "unknown"
    assert verdict.decidable is False
    assert verdict.model_bound is None


@pytest.mark.asyncio
async def test_bounded_search_checks_singleton_through_upper_bound(
    mace4_available: bool,
    prover_path: Path,
) -> None:
    if not mace4_available:
        pytest.skip("Mace4 is not installed")
    mace4 = Mace4Wrapper(prover_path)

    result = await mace4.find_model(["all x all y (x = y)"], max_domain_size=2)

    assert result["result"] == "model_found"
    assert result["model"]["domain_size"] == 1


@pytest.mark.asyncio
async def test_exact_singleton_search_does_not_call_unsupported_mace4_size(
    mace4_available: bool,
    prover_path: Path,
) -> None:
    if not mace4_available:
        pytest.skip("Mace4 is not installed")
    mace4 = Mace4Wrapper(prover_path)

    result = await mace4.find_model(["all x all y (x = y)"], domain_size=1)

    assert result["result"] == "model_found"
    assert result["model"]["domain_size"] == 1


@pytest.mark.asyncio
async def test_bounded_search_exhausts_mace4_sizes_after_singleton(
    mace4_available: bool,
    prover_path: Path,
) -> None:
    if not mace4_available:
        pytest.skip("Mace4 is not installed")
    mace4 = Mace4Wrapper(prover_path)

    result = await mace4.find_model(
        [
            "exists x exists y (x != y)",
            "all x all y (x = y)",
        ],
        max_domain_size=2,
    )

    assert result["result"] == "no_model_found"
