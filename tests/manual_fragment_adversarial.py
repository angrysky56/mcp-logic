"""Adversarial review of fragment detection.

The dangerous direction is a *false* ``decidable=True`` with too small a
bound: the server would then report "no model exists" when one exists at a
larger size — a confident wrong answer, which is the exact failure class
this project keeps trying to eliminate.

Two checks:

1. **Polarity traps.** A formula whose quantifier prefix only looks like
   BSR until negations are pushed in.
2. **Bound cross-validation.** For every theory declared decidable with
   bound B, ask Mace4 at B and again at B + 4. If a model turns up beyond
   the bound that was called complete, the bound is unsound.

    .venv/bin/python tests/manual_fragment_adversarial.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcp_logic.fragments import classify_fragment  # noqa: E402
from mcp_logic.mace4_wrapper import Mace4Wrapper  # noqa: E402

LADR = Path(__file__).resolve().parent.parent / "ladr" / "bin"

# (label, formulas, must_be_decidable_or_None_for_dont_care)
CASES: list[tuple[str, list[str], bool | None]] = [
    (
        "dense unbounded order (consistent, NO finite model)",
        [
            "all x all y (lt(x,y) -> -lt(y,x))",
            "all x all y all z ((lt(x,y) & lt(y,z)) -> lt(x,z))",
            "all x exists y (lt(x,y))",
            "all x all y (lt(x,y) -> exists z (lt(x,z) & lt(z,y)))",
            "exists a exists b (lt(a,b))",
        ],
        False,
    ),
    (
        "plain successor: all-exists needs a Skolem function",
        ["all x exists y (r(x,y))"],
        False,
    ),
    (
        "POLARITY TRAP: negated exists-forall is really forall-exists",
        ["-(exists x all y (r(x,y)))"],
        False,
    ),
    (
        "POLARITY TRAP: implication flips the antecedent",
        ["(all x exists y r(x,y)) -> p(a)"],
        None,
    ),
    (
        "POLARITY TRAP: iff carries both polarities",
        ["q(a) <-> (all x exists y r(x,y))"],
        None,
    ),
    (
        "genuine BSR: exists-then-forall",
        ["exists x all y (p(x) -> p(y))"],
        True,
    ),
    (
        "BSR needing exactly 4 elements",
        [
            "exists a exists b exists c exists d "
            "(a != b & a != c & a != d & b != c & b != d & c != d)"
        ],
        True,
    ),
    (
        "monadic, no equality",
        ["all x (p(x) -> q(x))", "exists x (p(x))", "exists x (-q(x))"],
        None,
    ),
    (
        "function symbol present: not BSR",
        ["all x (p(f(x)))"],
        None,
    ),
]


async def main() -> int:
    mace = Mace4Wrapper(LADR)
    problems = 0

    for label, formulas, expected in CASES:
        verdict = classify_fragment(formulas)
        flag = ""
        if expected is not None and verdict.decidable != expected:
            flag = "   <== WRONG"
            problems += 1

        print(
            f"\n{label}\n  fragment={verdict.fragment} "
            f"decidable={verdict.decidable} bound={verdict.model_bound}{flag}",
            flush=True,
        )

        if not verdict.decidable or verdict.model_bound is None:
            continue

        # Cross-validate the bound: nothing may appear beyond it.
        bound = verdict.model_bound
        at_bound = await mace.find_model(list(formulas), bound, timeout=20)
        beyond = await mace.find_model(list(formulas), bound + 4, timeout=20)

        found_at = at_bound.get("result") == "model_found"
        found_beyond = beyond.get("result") == "model_found"
        print(
            f"  mace4@{bound}={at_bound.get('result')} "
            f"mace4@{bound + 4}={beyond.get('result')}",
            flush=True,
        )

        if found_beyond and not found_at:
            print(
                "  !! UNSOUND BOUND: a model exists past a bound declared "
                "complete — 'no model exists' would be a lie here",
                flush=True,
            )
            problems += 1

    print(f"\nDONE. problems={problems}", flush=True)
    return problems


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
