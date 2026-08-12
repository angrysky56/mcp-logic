"""Adversarial guards on the fragment claim.

``tests/test_fragments.py`` checks that detection works. This file checks
the thing that would actually hurt: a *false* ``decidable=True``. When the
server believes a bounded search was complete it upgrades
``no_model_found`` to "No model exists" — so an over-eager verdict does
not degrade the answer, it inverts it.

Every case below is one where the quantifier prefix looks safer than it
is, or where the theory is consistent but has no finite model at all.
"""

from __future__ import annotations

import pytest

from mcp_logic.fragments import classify_counterexample, classify_fragment

DENSE_ORDER = [
    "all x all y (lt(x,y) -> -lt(y,x))",
    "all x all y all z ((lt(x,y) & lt(y,z)) -> lt(x,z))",
    "all x exists y (lt(x,y))",
    "all x all y (lt(x,y) -> exists z (lt(x,z) & lt(z,y)))",
    "exists a exists b (lt(a,b))",
]


class TestNoFiniteModelTheories:
    """Consistent theories with only infinite models must never be decided."""

    def test_dense_unbounded_order_is_not_decidable(self) -> None:
        # Satisfied by the rationals; no finite model exists. Claiming a
        # complete finite search here would report a consistent theory as
        # having "no model".
        verdict = classify_fragment(DENSE_ORDER)
        assert verdict.decidable is False
        assert verdict.model_bound is None

    def test_successor_needs_a_skolem_function(self) -> None:
        verdict = classify_fragment(["all x exists y (r(x,y))"])
        assert verdict.decidable is False


class TestPolarityTraps:
    """Prefixes that only look like BSR before negations are pushed in."""

    def test_negated_exists_forall_is_really_forall_exists(self) -> None:
        # Reads as exists-then-forall, but the negation inverts it, so
        # Skolemization yields a function and BSR does not apply.
        verdict = classify_fragment(["-(exists x all y (r(x,y)))"])
        assert verdict.decidable is False

    def test_iff_carries_both_polarities(self) -> None:
        # An existential under <-> appears positively and negatively at
        # once; the conservative answer is the only sound one.
        verdict = classify_fragment(["q(a) <-> (all x exists y r(x,y))"])
        assert verdict.decidable is False

    def test_antecedent_position_flips_a_universal(self) -> None:
        # In the antecedent, all-exists becomes exists-all, which IS BSR.
        # Getting this right matters as much as the rejections.
        verdict = classify_fragment(["(all x exists y r(x,y)) -> p(a)"])
        assert verdict.decidable is True
        assert verdict.fragment == "bsr"


class TestBoundsAreLargeEnough:
    """A bound smaller than the smallest model would invert the answer."""

    @pytest.mark.parametrize(
        ("formulas", "needed"),
        [
            (["all x exists y exists z (y != z & y != x & z != x)"], 3),
            (
                [
                    "exists x (p(x) & q(x))",
                    "exists x (p(x) & -q(x))",
                    "exists x (-p(x) & q(x))",
                    "exists x (-p(x) & -q(x))",
                ],
                4,
            ),
            (
                [
                    "exists a exists b exists c exists d "
                    "(a != b & a != c & a != d & b != c & b != d & c != d)"
                ],
                4,
            ),
        ],
    )
    def test_bound_covers_the_smallest_model(
        self, formulas: list[str], needed: int
    ) -> None:
        verdict = classify_fragment(formulas)
        assert verdict.decidable is True
        assert verdict.model_bound is not None
        assert verdict.model_bound >= needed, (
            f"bound {verdict.model_bound} is below the {needed} elements this "
            "theory requires — a complete search would wrongly report that no "
            "model exists"
        )


class TestCounterexampleTheory:
    """Classification must cover the negated goal, not just the premises."""

    def test_negated_conclusion_is_included(self) -> None:
        # The conclusion enters the countermodel theory NEGATED, so its
        # quantifiers flip. An exists-forall conclusion becomes forall-
        # exists, which needs a Skolem function and leaves the fragment.
        verdict = classify_counterexample(["p(a)"], "exists x all y (r(x,y))")
        assert verdict.decidable is False

    def test_conclusion_quantifiers_flip_the_other_way_too(self) -> None:
        # Mirror image: an all-exists conclusion negates to exists-all,
        # which IS in BSR even though the conclusion alone is not.
        verdict = classify_counterexample(["p(a)"], "all x exists y (r(x,y))")
        assert verdict.decidable is True

    def test_classic_invalid_syllogism_is_decidable(self) -> None:
        verdict = classify_counterexample(
            ["all x (cat(x) -> animal(x))", "exists x (animal(x) & dog(x))"],
            "exists x (cat(x) & dog(x))",
        )
        assert verdict.decidable is True
        assert verdict.fragment == "bsr"


class TestUnparseableInputFailsSafe:
    """Anything we cannot parse must not be promoted to a decision."""

    def test_garbage_is_not_decidable(self) -> None:
        verdict = classify_fragment(["all x ((("])
        assert verdict.decidable is False
        assert verdict.fragment == "unknown"
