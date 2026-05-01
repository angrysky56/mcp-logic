# Phase 1: Fix Existing Tests

**Goal:** Existing test suite passes cleanly on Linux with meaningful assertions.
**Status:** Complete

## Context

The current test suite has three primary issues:

1. `tests/test_proofs.py` is broken on Linux due to hardcoded Windows paths.
2. `tests/test_enhancements.py` is a manual script with no assertions, making it useless for CI.
3. The server log level is hardcoded to `DEBUG`, which creates excessive noise.

## Requirements

- [x] **TEST-01**: Fix `test_proofs.py` hardcoded Windows path.
- [x] **TEST-02**: Add assertions to `test_enhancements.py`.
- [x] **RQ-02**: Implement `--log-level` CLI argument in `server.py`.

## Tasks

### 1. Fix `test_proofs.py` (TEST-01)

- [x] Create a `pytest` fixture in `tests/conftest.py` (or locally) to discover the LADR binary path.
- [x] Fallback order: Environmental variable `LADR_PATH`, then `./ladr/bin`, then system path.
- [x] Use `pytest.mark.skipif` to skip Prover9 tests if binaries are not found, instead of crashing.
- [x] Refactor `test_proofs.py` to use the discovered path.

### 2. Modernize `test_enhancements.py` (TEST-02)

- [x] Rename/Refactor `tests/test_enhancements.py` into a proper `pytest` suite.
- [x] Replace all `print()` checks with `assert` statements.
- [x] Ensure `Mace4Wrapper` tests handle missing binaries gracefully (skip if not available).
- [x] Add tests for `CategoricalHelpers` and `syntax_validator`.

### 3. Configurable Logging (RQ-02)

- [x] Modify `src/mcp_logic/server.py:cli()` to accept `--log-level` (default: `INFO`).
- [x] Update `main()` and `logging.basicConfig` to use the provided log level.
- [x] Verify that `DEBUG` output is suppressed by default.

## Verification Plan

### Automated Tests

- [x] Run `pytest tests/test_hcc_prover.py tests/test_vfe_engine.py tests/test_formula_ast.py` (Should pass 100%).
- [x] Run `pytest tests/test_enhancements.py` (Should pass 100% with assertions).
- [x] Run `pytest tests/test_proofs.py` (Should either pass or skip, no Windows errors).

### Manual Verification

- [ ] Run `python -m mcp_logic.server --prover-path ./ladr/bin` and verify output level is `INFO`.
- [ ] Run `python -m mcp_logic.server --prover-path ./ladr/bin --log-level DEBUG` and verify `DEBUG` logs appear.
