"""Live check: does faithfulness detection catch real formalization drift?

Runs the questions that failed in a live smoke run, repeatedly, so both
outcomes get exercised — the model formalizes them correctly most of the
time and drifts occasionally, and the point is that the drift is now
visible instead of arriving dressed as a proof.

    .venv/bin/python tests/manual_faithfulness_live.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcp_logic.logic_advisor import LogicAdvisor  # noqa: E402
from mcp_logic.server import LogicEngine, _SolverBridge  # noqa: E402

logging.basicConfig(level=logging.ERROR)
PROVER_PATH = Path(__file__).resolve().parent.parent / "ladr" / "bin"
REPS = 3

QUESTIONS = [
    "If x is an integer greater than 0, is 2 times x greater than x?",
    "Alice's age is greater than 0. Does it follow that her age is over 50?",
    "All humans are mortal. Socrates is a human. Is Socrates mortal?",
    "Is every prime number greater than 2 odd?",
]


async def main() -> int:
    engine = LogicEngine(str(PROVER_PATH))
    advisor = LogicAdvisor(_SolverBridge(engine), n_gpu_layers=-1, cache_size=0)
    await advisor.ensure_model()

    for question in QUESTIONS:
        print("=" * 74, flush=True)
        print("Q:", question, flush=True)
        for rep in range(REPS):
            result = await advisor.solve(question, use_cache=False)
            report = result.faithfulness
            flag = "FLAGGED" if report.looks_suspicious else "clean  "
            premises = result.formalization.get(
                "premises", result.formalization.get("constraints", [])
            )
            print(
                f"  [{rep}] {flag} status={result.status.value:<20} "
                f"premises={len(premises)}",
                flush=True,
            )
            if report.looks_suspicious:
                for warning in report.warnings:
                    print(f"        ! {warning[:100]}", flush=True)
            if report.reads_as:
                print(f"        reads: {report.reads_as[:120]}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
