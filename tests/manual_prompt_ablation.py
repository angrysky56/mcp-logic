"""Is the advisor's weakness the MODEL or the PROMPT?

Runs the same questions through the same model under three prompt designs
and scores each by whether Prover9/Mace4 accepts the resulting plan.  Not
part of the pytest suite — needs the 3.3 GB model and a GPU.

    .venv/bin/python tests/manual_prompt_ablation.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcp_logic.logic_advisor import (  # noqa: E402
    _FORMALIZE_SYSTEM,
    LogicAdvisor,
    _is_solver_error,
    normalize_plan,
)
from mcp_logic.server import LogicEngine, _SolverBridge  # noqa: E402

logging.basicConfig(level=logging.ERROR)

PROVER_PATH = Path(__file__).resolve().parent.parent / "ladr" / "bin"
REPS = 3

# ── Variant B: the current prompt plus worked examples ──────────────────
# The model card's strongest lanes are translation-shaped (lean_formalize,
# semantic_parse), so showing the mapping may matter more than describing it.
_FEWSHOT = _FORMALIZE_SYSTEM + """
## Worked Examples

Question: All humans are mortal. Socrates is a human. Does it follow that Socrates is mortal?
{"tool": "prove", "premises": ["all x (human(x) -> mortal(x))", "human(socrates)"], "conclusion": "mortal(socrates)"}

Question: All dogs are loyal. Some pets are dogs. Does it follow that some pets are loyal?
{"tool": "prove", "premises": ["all x (dog(x) -> loyal(x))", "exists x (pet(x) & dog(x))"], "conclusion": "exists x (pet(x) & loyal(x))"}

Question: Every bird flies. Tweety is a bird. Is there something that flies?
{"tool": "prove", "premises": ["all x (bird(x) -> flies(x))", "bird(tweety)"], "conclusion": "exists x flies(x)"}

Remember: EVERY premise and conclusion must be a Prover9 formula, never an \
English sentence. "All cats are animals" is WRONG; \
"all x (cat(x) -> animal(x))" is RIGHT.
"""

# ── Variant C: play to the model's trained task (NL -> FOL only) ────────
_TRANSLATE_SYSTEM = """\
You are a first-order logic translator. Translate each numbered English \
sentence into a single Prover9 formula.

Syntax: all x (...), exists x (...), -> & | - , predicates lowercase with \
arguments, constants lowercase, no trailing period.

Output ONE formula per line, numbered to match the input, and nothing else.
Example:
1. all x (human(x) -> mortal(x))
2. human(socrates)
"""

QUESTIONS: list[tuple[str, list[str], str]] = [
    (
        "cats/dogs (existential, invalid)",
        ["All cats are animals", "Some animals are dogs"],
        "Some cats are dogs",
    ),
    (
        "penguins (existential, invalid)",
        ["Some birds can fly", "All penguins are birds"],
        "Some penguins can fly",
    ),
    (
        "students (universal, valid)",
        ["Every student passed", "John is a student"],
        "John passed",
    ),
]


def _question_text(premises: list[str], conclusion: str) -> str:
    prem = ". ".join(premises)
    return f"{prem}. Does it follow that {conclusion.lower()}?"


def _parse_numbered(text: str, count: int) -> list[str]:
    """Pull ``N. formula`` lines out of a translation response."""
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        _, _, formula = line.partition(".")
        formula = formula.strip()
        if formula:
            out.append(formula)
    return out[:count]


async def run_variant(
    advisor: LogicAdvisor, name: str, system: str, translate: bool
) -> None:
    wins = 0
    total = 0
    english_leaks = 0

    for _label, premises, conclusion in QUESTIONS:
        for _ in range(REPS):
            total += 1
            if translate:
                numbered = "\n".join(
                    f"{i}. {s}" for i, s in enumerate([*premises, conclusion], 1)
                )
                raw = await advisor._llm_call(system=system, user=numbered)
                formulas = _parse_numbered(raw, len(premises) + 1)
                if len(formulas) < len(premises) + 1:
                    continue
                plan = {
                    "tool": "prove",
                    "premises": formulas[:-1],
                    "conclusion": formulas[-1],
                }
            else:
                raw = await advisor._llm_call(
                    system=system, user=_question_text(premises, conclusion)
                )
                plan = LogicAdvisor._parse_plan(raw)

            plan = normalize_plan(plan)
            if plan.get("tool") in (None, "none"):
                continue

            # An English premise is the specific failure being chased.
            if any(
                " are " in str(p) or " is a " in str(p)
                for p in plan.get("premises", [])
            ):
                english_leaks += 1

            output = await advisor._run_solver(plan)
            if not _is_solver_error(output):
                wins += 1

    print(
        f"{name:<28} solver-accepted {wins}/{total}"
        f"   english-leaks {english_leaks}/{total}",
        flush=True,
    )


async def main() -> None:
    engine = LogicEngine(str(PROVER_PATH))
    advisor = LogicAdvisor(_SolverBridge(engine), n_gpu_layers=-1)
    await advisor.ensure_model()

    await run_variant(advisor, "A: current (zero-shot)", _FORMALIZE_SYSTEM, False)
    await run_variant(advisor, "B: + worked examples", _FEWSHOT, False)
    await run_variant(advisor, "C: native translate task", _TRANSLATE_SYSTEM, True)


if __name__ == "__main__":
    asyncio.run(main())
