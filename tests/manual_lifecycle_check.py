"""Verify caching, idle unloading and countermodel routing on real hardware.

Unit tests cover the logic with a fake model; this checks the parts that
only mean anything with 3.3 GB of weights actually loaded — VRAM is really
released, a cached answer really skips the GPU.

    .venv/bin/python tests/manual_lifecycle_check.py
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcp_logic.logic_advisor import LogicAdvisor  # noqa: E402
from mcp_logic.server import LogicEngine, _SolverBridge  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

PROVER_PATH = Path(__file__).resolve().parent.parent / "ladr" / "bin"
SYLLOGISM = "All humans are mortal. Socrates is a human. Is Socrates mortal?"
INVALID = (
    "All cats are animals. Some animals are dogs. "
    "Does it follow that some cats are dogs?"
)


def gpu_mib() -> int:
    """Current GPU memory use in MiB, or -1 if nvidia-smi is unavailable."""
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return -1
    return int(out.stdout.strip().splitlines()[0])


async def main() -> int:
    engine = LogicEngine(str(PROVER_PATH))
    advisor = LogicAdvisor(
        _SolverBridge(engine),
        n_gpu_layers=-1,
        cache_size=16,
        idle_unload_seconds=8.0,
    )

    failures = 0

    # ── Cache ───────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    first = await advisor.solve(SYLLOGISM)
    cold = time.perf_counter() - t0

    t1 = time.perf_counter()
    second = await advisor.solve(SYLLOGISM)
    warm = time.perf_counter() - t1

    print(f"\ncold solve: {cold:.2f}s | cached solve: {warm:.4f}s", flush=True)
    print(f"answers identical: {first.answer == second.answer}", flush=True)
    if warm > cold / 10:
        print("!! cache did not obviously help", flush=True)
        failures += 1
    if "(served from cache)" not in second.steps[-1]:
        print("!! second solve was not served from cache", flush=True)
        failures += 1

    # ── Countermodel routing ────────────────────────────────────────────
    result = await advisor.solve(INVALID)
    has_counter = "countermodel" in result.solver_output
    print(f"\ninvalid inference verified={result.verified}", flush=True)
    print(f"countermodel attached: {has_counter}", flush=True)
    if has_counter:
        print(f"countermodel: {result.solver_output['countermodel']}", flush=True)
    print(f"ANSWER: {result.answer[:300]}", flush=True)

    # ── Idle unload ─────────────────────────────────────────────────────
    loaded_mib = gpu_mib()
    print(f"\nVRAM while loaded: {loaded_mib} MiB", flush=True)
    print("waiting out the 8s idle window...", flush=True)
    await asyncio.sleep(11)

    print(f"advisor.loaded after idle: {advisor.loaded}", flush=True)
    idle_mib = gpu_mib()
    print(f"VRAM after unload: {idle_mib} MiB", flush=True)
    if advisor.loaded:
        print("!! model was not unloaded", flush=True)
        failures += 1

    # ── Reload on demand ────────────────────────────────────────────────
    t2 = time.perf_counter()
    again = await advisor.solve("Is p or not p a tautology?")
    print(f"\nreload + solve: {time.perf_counter() - t2:.2f}s", flush=True)
    print(f"answer: {again.answer[:120]}", flush=True)
    if not again.verified:
        print("!! post-reload solve was not verified", flush=True)
        failures += 1

    await advisor.unload()
    print(f"\nDONE. failures={failures}", flush=True)
    return failures


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
