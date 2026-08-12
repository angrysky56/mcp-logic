# Phase 5: Cleanup

## Goal

Final polish and cleanup of the codebase, documentation, and Docker configuration.

## Requirements

- CLEAN-01: Configurable Mace4 timeout
- CLEAN-02: Gitignore `docker-env/`
- CLEAN-03: Fix Dockerfile `EXPOSE`
- CLEAN-04: Restructure `mcp_logic_agent.md`

## Plans

### Wave 1: Code & Config

1. **CLEAN-01: Configurable Mace4 timeout**
   - Update `Mace4Wrapper.find_model` and `find_counterexample` to accept `timeout: int`.
   - Thread this to `subprocess.run(..., timeout=...)` and use it in `assign(max_seconds, ...)` in the input file.
2. **CLEAN-02: Gitignore `docker-env/`**
   - Add `docker-env/` to `.gitignore`.
3. **CLEAN-03: Fix Dockerfile `EXPOSE`**
   - Remove misleading `EXPOSE` instructions from `Dockerfile`.

### Wave 2: Documentation

4. **CLEAN-04: Restructure `mcp_logic_agent.md`**
   - Update `mcp_logic_agent.md` to have structured documentation (tool descriptions, parameter examples, usage patterns).

## Verification

- Run all tests to ensure no regressions.
- Verify `Dockerfile` no longer has `EXPOSE`.
- Verify `mcp_logic_agent.md` is updated.
- Verify timeout works in Mace4 by setting a very low timeout.
