"""Deciding when a Prover9 translation has to become SMT-LIB.

The model translates into Prover9 first, because one narrow translation
task is what it does reliably. If that translation reaches for arithmetic —
which Prover9 has no theory for — it gets a second, equally narrow SMT-LIB
call. The trigger reads the *formulas*, never the question's wording.

Both error directions matter:

* a miss sends ``x > 0`` to a prover that cannot interpret it;
* a false positive sends ordinary first-order logic to Z3, and the strict
  order relation ``lt(x, y)`` is exactly the shape that invites one.
"""

from __future__ import annotations

import pytest

from mcp_logic.logic_advisor import needs_smt_retranslation

DENSE_ORDER = [
    "all x all y (lt(x,y) -> -lt(y,x))",
    "all x all y all z ((lt(x,y) & lt(y,z)) -> lt(x,z))",
    "all x exists y (lt(x,y))",
]


class TestStaysOnProver9:
    """Pure first-order logic must never be diverted to Z3."""

    @pytest.mark.parametrize(
        "formulas",
        [
            ["all x (cat(x) -> animal(x))", "exists x (animal(x) & dog(x))"],
            ["all x (human(x) -> mortal(x))", "human(socrates)"],
            # Equality is FOL, not arithmetic.
            ["mult(a,b) = u", "mult(a,b) = v"],
            ["all x (mult(e,x) = x)", "all x (mult(x,inv(x)) = e)"],
            # `->` and `<->` contain > and <; they must not be misread.
            ["all x (p(x) <-> q(x))"],
            ["all x (p(x) -> q(x))"],
            # A relation NAMED like an ordering is still just a relation.
            DENSE_ORDER,
            ["exists x exists y (x != y)"],
        ],
    )
    def test_no_retranslation(self, formulas: list[str]) -> None:
        assert needs_smt_retranslation(formulas) is False


class TestNeedsZ3:
    """Anything Prover9 cannot interpret must be re-translated."""

    @pytest.mark.parametrize(
        "formulas",
        [
            ["all x (x > 0 -> 2 * x > x)"],
            # The exact garbage the merged prompt produced.
            ["(gt x (2 * x))"],
            ["exists x (0 < x < 11 & 3 | x)"],
            ["age >= 18"],
            ["all x (p(x) -> x + 1 > x)"],
            # A numeral used as a term.
            ["p(0)"],
        ],
    )
    def test_retranslation_triggered(self, formulas: list[str]) -> None:
        assert needs_smt_retranslation(formulas) is True

    def test_one_arithmetic_formula_is_enough(self) -> None:
        mixed = ["all x (human(x) -> mortal(x))", "age > 18"]
        assert needs_smt_retranslation(mixed) is True

    def test_empty_input_is_not_arithmetic(self) -> None:
        assert needs_smt_retranslation([]) is False
