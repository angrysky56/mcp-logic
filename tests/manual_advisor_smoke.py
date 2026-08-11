"""Manual end-to-end smoke test for the onboard logic advisor.

Not part of the pytest suite (loads a 3.3 GB model). Run directly:

    .venv/bin/python tests/manual_advisor_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcp_logic.logic_advisor import LogicAdvisor  # noqa: E402
from mcp_logic.server import LogicEngine  # noqa: E402
from mcp_logic.server import _SolverBridge  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

PROVER_PATH = Path(__file__).resolve().parent.parent / "ladr" / "bin"

CASES: list[tuple[str, str]] = [
    (
        "valid syllogism",
        "All humans are mortal. Socrates is a human. Does it follow that "
        "Socrates is mortal?",
    ),
    (
        "invalid inference (needs counterexample)",
        "All cats are animals. Some animals are dogs. Does it follow that "
        "some cats are dogs?",
    ),
    (
        "propositional tautology",
        "Is the formula 'p or not p' a tautology, a contradiction, or " "contingent?",
    ),
    (
        "satisfiability / model finding",
        "Find a world where every element has a successor and no element is "
        "its own successor.",
    ),
    (
        "arithmetic entailment (Z3 route)",
        "If x is an integer greater than 0, is 2 times x greater than x?",
    ),
    (
        "arithmetic refutation (Z3 route)",
        "Alice's age is greater than 0. Does it follow that her age is over 50?",
    ),
    (
        "arithmetic satisfiability (Z3 route)",
        "Is there an integer between 0 and 10 that is divisible by 3?",
    ),
    (
        "nonsense input (should degrade gracefully)",
        "What is your favourite colour?",
    ),
]


async def main() -> int:
    engine = LogicEngine(str(PROVER_PATH))
    advisor = LogicAdvisor(_SolverBridge(engine), n_gpu_layers=-1, n_ctx=4096)

    t0 = time.perf_counter()
    await advisor.ensure_model()
    print(f"\n[model load] {time.perf_counter() - t0:.1f}s\n", flush=True)

    failures = 0
    for name, question in CASES:
        print("=" * 70, flush=True)
        print(f"CASE: {name}\nQ: {question}", flush=True)
        t1 = time.perf_counter()
        try:
            result = await advisor.solve(question)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"!! EXCEPTION: {type(exc).__name__}: {exc}", flush=True)
            continue
        dt = time.perf_counter() - t1
        print(f"[{dt:.1f}s] plan: {json.dumps(result.formalization)}", flush=True)
        print(f"solver: {json.dumps(result.solver_output)[:400]}", flush=True)
        print(f"ANSWER: {result.answer[:800]}\n", flush=True)

    print(f"\nDONE. exceptions={failures}", flush=True)
    return failures


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
