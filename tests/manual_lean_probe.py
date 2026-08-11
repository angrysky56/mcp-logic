"""Does TwIL-LM3 actually emit usable Lean 4 theorem statements?

The model card reports ``lean_formalize`` as its strongest generative lane
(token-F1 0.5869), but that was measured on bf16 weights through vLLM, not
the Q8_0 GGUF this project runs.  Before committing to a Lean toolchain,
check the cheap thing: what fraction of statements are even syntactically
plausible?

No Lean install required — this scores structure, not compilation, which is
an upper bound on how well a real Lean integration could do.

    .venv/bin/python tests/manual_lean_probe.py
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcp_logic.logic_advisor import LogicAdvisor, _strip_think_blocks  # noqa: E402
from mcp_logic.server import LogicEngine, _SolverBridge  # noqa: E402

logging.basicConfig(level=logging.ERROR)

PROVER_PATH = Path(__file__).resolve().parent.parent / "ladr" / "bin"

_LEAN_SYSTEM = """\
You are a Lean 4 formalizer. Translate the statement into a single Lean 4 \
theorem declaration with `sorry` as the proof.

Output ONLY the Lean code, no explanation. Example:
theorem add_comm_nat (a b : Nat) : a + b = b + a := sorry
"""

STATEMENTS = [
    "For all natural numbers a and b, a + b equals b + a.",
    "For every natural number n, n + 0 = n.",
    "If a divides b and b divides c then a divides c.",
    "The sum of two even integers is even.",
    "For all real numbers x, x squared is non-negative.",
    "There is no largest natural number.",
    "If a list is empty its length is zero.",
    "For all sets A and B, A intersect B is a subset of A.",
    "Every prime number greater than 2 is odd.",
    "For all natural numbers n, n <= n + 1.",
]

# Structural checks — necessary conditions for Lean 4 to accept it at all.
_THEOREM_RE = re.compile(r"\b(theorem|lemma|example)\b")
_ASSIGN_RE = re.compile(r":=")


def score(code: str) -> tuple[bool, str]:
    """Return (plausible, reason) for a candidate Lean declaration."""
    text = code.strip()
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("```")
        )
        text = text.strip()

    if not _THEOREM_RE.search(text):
        return False, "no theorem/lemma keyword"
    if ":" not in text:
        return False, "no type ascription"
    if not _ASSIGN_RE.search(text):
        return False, "no := body"
    if text.count("(") != text.count(")"):
        return False, "unbalanced parens"
    return True, "plausible"


async def main() -> None:
    engine = LogicEngine(str(PROVER_PATH))
    advisor = LogicAdvisor(_SolverBridge(engine), n_gpu_layers=-1)
    await advisor.ensure_model()

    good = 0
    for statement in STATEMENTS:
        raw = await advisor._llm_call(system=_LEAN_SYSTEM, user=statement)
        code = _strip_think_blocks(raw)
        ok, reason = score(code)
        good += int(ok)
        first_line = next(
            (line for line in code.splitlines() if line.strip()), "(empty)"
        )
        print(f"[{'OK ' if ok else 'BAD'}] {reason:<22} {first_line[:100]}", flush=True)

    print(f"\nstructurally plausible: {good}/{len(STATEMENTS)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
