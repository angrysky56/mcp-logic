"""The shipped axiom sets must actually characterise what they claim.

An axiom set can be consistent, satisfiable and completely vacuous at the
same time — `find_model` will happily return a "model" of axioms that say
nothing.  The only real check is whether the intended theorems follow, so
these tests prove textbook results from the shipped axioms.

This caught a live hazard.  The previous relational encoding obtained
uniqueness of products from an *unquantified* variable inside the
associativity axiom: implicit universal quantification made it work, and
"fixing" the apparent typo turned the whole axiom into the tautology
``xyz = xyz``, silently deleting its content while every consistency check
still passed.  ``test_associativity_is_not_vacuous`` pins that class of
failure for good.
"""

from __future__ import annotations

import pytest

from mcp_logic.categorical_helpers import group_axioms, monoid_axioms


@pytest.fixture(scope="module")
def prover() -> object:
    """A LogicEngine pointed at the bundled LADR binaries."""
    from pathlib import Path

    from mcp_logic.server import LogicEngine

    ladr = Path(__file__).resolve().parent.parent / "ladr" / "bin"
    if not (ladr / "prover9").exists():
        pytest.skip("LADR binaries are not built")
    return LogicEngine(str(ladr))


async def _prove(prover: object, premises: list[str], conclusion: str) -> dict:
    path = prover.create_input_file(premises, conclusion)  # type: ignore[attr-defined]
    return await prover.run_prover(path, timeout=30)  # type: ignore[attr-defined]


class TestMonoidAxioms:
    """A monoid must have exactly one identity, and it must associate."""

    @pytest.mark.asyncio
    async def test_identity_is_unique(self, prover: object) -> None:
        # If f is also a left identity, f must be e.
        result = await _prove(
            prover,
            [*monoid_axioms(), "all x (mult(f,x) = x)"],
            "f = e",
        )
        assert result["result"] == "proved"

    @pytest.mark.asyncio
    async def test_associativity_is_not_vacuous(self, prover: object) -> None:
        # The regression guard: a tautological associativity axiom would
        # leave this unprovable.
        result = await _prove(
            prover,
            monoid_axioms(),
            "all a all b all c all d (mult(mult(mult(a,b),c),d) "
            "= mult(a,mult(b,mult(c,d))))",
        )
        assert result["result"] == "proved"

    @pytest.mark.asyncio
    async def test_products_are_single_valued(self, prover: object) -> None:
        # Function symbols give this by construction; the old relational
        # encoding had to derive it, and could silently lose it.
        result = await _prove(
            prover,
            [*monoid_axioms(), "mult(a,b) = u", "mult(a,b) = v"],
            "u = v",
        )
        assert result["result"] == "proved"


class TestGroupAxioms:
    """Textbook group theory should fall straight out."""

    @pytest.mark.asyncio
    async def test_double_inverse(self, prover: object) -> None:
        # Not even expressible without a named inverse function.
        result = await _prove(prover, group_axioms(), "all x (inv(inv(x)) = x)")
        assert result["result"] == "proved"

    @pytest.mark.asyncio
    async def test_inverse_of_product_reverses_order(self, prover: object) -> None:
        result = await _prove(
            prover,
            group_axioms(),
            "all x all y (inv(mult(x,y)) = mult(inv(y),inv(x)))",
        )
        assert result["result"] == "proved"

    @pytest.mark.asyncio
    async def test_left_cancellation(self, prover: object) -> None:
        result = await _prove(
            prover,
            [*group_axioms(), "mult(a,b) = mult(a,c)"],
            "b = c",
        )
        assert result["result"] == "proved"

    @pytest.mark.asyncio
    async def test_identity_is_its_own_inverse(self, prover: object) -> None:
        result = await _prove(prover, group_axioms(), "inv(e) = e")
        assert result["result"] == "proved"

    @pytest.mark.asyncio
    async def test_groups_are_not_forced_commutative(self, prover: object) -> None:
        # A sanity check in the other direction: the axioms must NOT prove
        # commutativity, or they are too strong and describe abelian groups.
        result = await _prove(
            prover, group_axioms(), "all x all y (mult(x,y) = mult(y,x))"
        )
        assert result["result"] != "proved"
