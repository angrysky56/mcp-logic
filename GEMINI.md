# mcp-logic — Project Guide (Gemini/Antigravity)

## Project Summary

**mcp-logic** is an MCP server exposing 8 logical reasoning tools to AI clients (Claude Desktop). Current milestone: **v0.3.0 Hardening** — fixing 13 known issues, no new features.

## Active Milestone

**v0.3.0 — Hardening & Correctness** | 5 phases | 13 requirements

| Phase | Goal                                         | Status         |
| ----- | -------------------------------------------- | -------------- |
| 1     | Fix Existing Tests (TEST-01, TEST-02, RQ-02) | ⬜ Not started |
| 2     | CI Pipeline (TEST-03)                        | ⬜ Not started |
| 3     | Async Runtime Fix (RQ-01)                    | ⬜ Not started |
| 4     | Correctness Fixes (CORR-01–04)               | ⬜ Not started |
| 5     | Cleanup (CLEAN-01–04)                        | ⬜ Not started |

## GSD Workflow

This project uses GSD (Get Shit Done) for structured execution.

**Key commands:**

- `/gsd-plan-phase 1` — Plan Phase 1 in detail
- `/gsd-execute-phase 1` — Execute Phase 1 plans
- `/gsd-progress` — Check current status
- `/gsd-verify-work` — Verify phase deliverables

**Config:** `.planning/config.json` — YOLO mode, Standard granularity, plan_check + verifier enabled

## Architecture Quick Reference

- **Entry point:** `src/mcp_logic/server.py:cli()`
- **Tool dispatch:** `server.py:handle_call_tool()` — 8 MCP tools
- **Prover9 wrapper:** `server.py:LogicEngine`
- **Mace4 wrapper:** `mace4_wrapper.py:Mace4Wrapper`
- **HCC prover:** `hcc_prover.py:check_contingency()`
- **VFE engine:** `vfe_engine.py:abductive_explain()`
- **Formula parser:** `formula_ast.py:parse()`
- **Binaries:** `ladr/bin/prover9`, `ladr/bin/mace4`

## Top Known Issues (for context)

| ID      | File                 | Issue                                       |
| ------- | -------------------- | ------------------------------------------- |
| RQ-01   | server.py            | Blocking subprocess.run() in async handlers |
| RQ-02   | server.py            | Hardcoded DEBUG log level                   |
| TEST-01 | test_proofs.py       | Windows path breaks Linux                   |
| TEST-02 | test_enhancements.py | No assertions                               |
| TEST-03 | (missing)            | No CI pipeline                              |
| CORR-01 | mace4_wrapper.py     | Duplicate data in \_parse_model()           |
| CORR-02 | server.py            | Fragile string-match smart routing          |

## Conventions

- Python 3.10+, `uv` for env management
- Frozen dataclasses for result types (`ContingencyResult`, `AbductionResult`)
- Private methods prefixed `_`; subprocess calls in `finally` cleanup temp files
- Trunk for linting: `ruff`, `black`, `isort`, `bandit`
- Commits: Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `ci:`, `docs:`)

## Planning Artifacts

| File                        | Purpose                      |
| --------------------------- | ---------------------------- |
| `.planning/PROJECT.md`      | Project context and goals    |
| `.planning/REQUIREMENTS.md` | 13 requirements with REQ-IDs |
| `.planning/ROADMAP.md`      | 5-phase plan                 |
| `.planning/STATE.md`        | Current progress             |
| `.planning/codebase/`       | Architecture map (7 docs)    |
