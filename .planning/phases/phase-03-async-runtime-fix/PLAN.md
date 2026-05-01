# Phase 3: Async Runtime Fix — PLAN

Goal: MCP server no longer blocks the event loop during proof searches.

## 1. Research & Baseline

- [x] Verify `asyncio.create_subprocess_exec` behavior on Linux with `cwd`.
- [x] Confirm `asyncio.wait_for` is the correct way to implement timeouts for subprocesses.
- [x] Ensure `communicate()` correctly captures `stdout` and `stderr` as bytes.

## 2. Refactor Mace4Wrapper (RQ-01)

- [x] Change `_run_mace4` to `async def _run_mace4`.
- [x] Replace `subprocess.run` with `asyncio.create_subprocess_exec`.
- [x] Implement timeout using `asyncio.wait_for`.
- [x] Update `find_model` and `find_counterexample` to be `async def` and `await _run_mace4`.

## 3. Refactor LogicEngine (RQ-01)

- [x] Change `_run_prover` to `async def _run_prover`.
- [x] Replace `subprocess.run` with `asyncio.create_subprocess_exec`.
- [x] Implement timeout using `asyncio.wait_for`.
- [x] Ensure cleanup of temp files in `finally` block remains robust.

## 4. Update Server Tool Handlers

- [x] Update `handle_call_tool` for `name == "prove"` to `await engine._run_prover()`.
- [x] Update `handle_call_tool` for `name == "find_model"` to `await engine.mace4.find_model()`.
- [x] Update `handle_call_tool` for `name == "find_counterexample"` to `await engine.mace4.find_counterexample()`.

## 5. Test Suite Modernization

- [x] Add `pytest-asyncio` to `pyproject.toml` or install manually for local verification.
- [x] Update `tests/test_proofs.py` to use `async def` and `await`.
- [x] Update `tests/test_enhancements.py` to use `async def` and `await`.
- [x] Add `@pytest.mark.asyncio` to all tests that call async methods.

## 6. Verification Loop

- [x] Run `pytest tests/test_proofs.py tests/test_enhancements.py`.
- [x] Verify 100% pass rate.
- [x] Run `trunk check` to ensure no new linting issues (especially around async).
- [x] Manual check: verify no interleaved output or deadlocks under load.
