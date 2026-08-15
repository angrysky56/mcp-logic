"""Can the local model read a formalization back into English?

Everything built so far hardens the path from *formula* to *verdict*.
Nothing checks the step from *question* to *formula* — and that step failed
silently in a live run: a premise was dropped, and a goal was negated, both
returning ``status: REFUTED`` with a machine-checked answer to a question
nobody asked.

Back-translation is the candidate fix, but it only works if the model can
render Prover9/SMT-LIB back into faithful English. Probe that before
building anything on top of it.

    .venv/bin/python tests/manual_backtranslation_probe.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcp_logic.logic_advisor import LogicAdvisor, _strip_think_blocks  # noqa: E402
from mcp_logic.server import LogicEngine, _SolverBridge  # noqa: E402

logging.basicConfig(level=logging.ERROR)
PROVER_PATH = Path(__file__).resolve().parent.parent / "ladr" / "bin"

_BACKTRANSLATE_SYSTEM = """\
You are a formal logic reader. Translate each formal statement into one \
plain English sentence. Do not judge, solve or comment — only translate.

Output one line per input, in order, prefixed with its label.

Example input:
PREMISE: all x (human(x) -> mortal(x))
GOAL: mortal(socrates)

Example output:
PREMISE: Every human is mortal.
GOAL: Socrates is mortal.
"""

# (label, original question, formalization actually produced)
CASES: list[tuple[str, str, str]] = [
    (
        "GOOD: faithful",
        "If x is an integer greater than 0, is 2 times x greater than x?",
        "PREMISE: (> x 0)\nGOAL: (> (* 2 x) x)",
    ),
    (
        "BAD: premise dropped (observed live)",
        "If x is an integer greater than 0, is 2 times x greater than x?",
        "GOAL: (> (* 2 x) x)",
    ),
    (
        "BAD: goal negated (observed live)",
        "Alice's age is greater than 0. Does it follow that her age is over 50?",
        "PREMISE: (> age 0)\nGOAL: (not (> age 50))",
    ),
    (
        "GOOD: faithful FOL",
        "All cats are animals. Some animals are dogs. Do some cats bark?",
        "PREMISE: all x (cat(x) -> animal(x))\n"
        "PREMISE: exists x (animal(x) & dog(x))\n"
        "GOAL: exists x (cat(x) & barks(x))",
    ),
    (
        "BAD: hypothesis silently dropped (the Lean failure)",
        "Is every prime number greater than 2 odd?",
        "PREMISE: all p (gt(p, two) -> odd(p))",
    ),
]


async def main() -> int:
    engine = LogicEngine(str(PROVER_PATH))
    advisor = LogicAdvisor(_SolverBridge(engine), n_gpu_layers=-1, cache_size=0)
    await advisor.ensure_model()

    for label, question, formalization in CASES:
        reading = await advisor._llm_call(
            system=_BACKTRANSLATE_SYSTEM, user=formalization
        )
        text = " ".join(
            line.strip()
            for line in _strip_think_blocks(reading).splitlines()
            if line.strip()
        )
        print("=" * 72, flush=True)
        print(
            f"{label}\n  asked : {question}\n  formal: "
            f"{formalization.replace(chr(10), ' | ')}\n  reads : {text[:280]}",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
