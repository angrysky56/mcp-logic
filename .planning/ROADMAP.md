# Roadmap — mcp-logic Hardening

**Milestone:** v0.3.0 — Hardening & Correctness
**Phases:** 5 | **Requirements:** 13 | **Coverage:** 100%

---

## Phase 1: Fix Existing Tests

**Goal:** Existing test suite passes cleanly on Linux with meaningful assertions.

**Requirements:** TEST-01, TEST-02, RQ-02

**Rationale:** Fix the test infrastructure before touching anything else — so subsequent phases can run the suite and catch regressions. Log level fix (RQ-02) is included here because it reduces test noise immediately.

**Plans:**
1. Fix `test_proofs.py` hardcoded Windows path — pytest fixture + `skipif` guard for Linux `ladr/bin/`
2. Add assertions to `test_enhancements.py` — replace all print-only checks
3. Add `--log-level` CLI arg to `server.py` — remove hardcoded DEBUG

**Success criteria:**
1. `pytest tests/test_hcc_prover.py tests/test_vfe_engine.py tests/test_formula_ast.py tests/test_enhancements.py` passes with 0 failures on Linux
2. `pytest tests/test_proofs.py` either passes (if LADR binaries present) or is explicitly skipped — no hardcoded Windows path errors
3. Starting the server with no `--log-level` arg produces `INFO`-level output, not `DEBUG`
4. `pytest tests/test_enhancements.py -v` shows assertion failures (not silent green) when Mace4 returns unexpected results

---

## Phase 2: CI Pipeline

**Goal:** Automated quality gate runs on every push to main.

**Requirements:** TEST-03

**Rationale:** CI must be added after tests are reliable (Phase 1) so it passes from day 1. A failing CI from day 1 is worse than no CI.

**Plans:**
1. Write `.github/workflows/ci.yml` — install deps, build LADR, run pytest, run trunk check
2. Add `trunk check` baseline annotation for any pre-existing lint issues

**Success criteria:**
1. GitHub Actions workflow runs on every push to `main` and every PR
2. `pytest` step runs all tests in the CI environment with LADR binaries built from source
3. `trunk check` step passes (or pre-existing issues are baselined so new issues are caught)
4. Workflow completes in under 10 minutes
5. Badge can be added to README showing CI status

---

## Phase 3: Async Runtime Fix

**Goal:** MCP server no longer blocks the event loop during proof searches.

**Requirements:** RQ-01

**Rationale:** Isolated phase because async refactoring touches the core request path — safest to do with CI running (Phase 2 complete) so any regression is immediately caught.

**Plans:**
1. Refactor `LogicEngine._run_prover()` and `Mace4Wrapper._run_mace4()` to use `asyncio.create_subprocess_exec()`
2. Update `server.py:handle_call_tool()` to `await` the subprocess calls
3. Verify all 8 tool handlers work correctly with the async path

**Success criteria:**
1. All 8 MCP tools return correct results after the async refactor
2. `pytest` passes with 0 failures after refactor
3. Two concurrent tool requests do not deadlock or produce interleaved output
4. `asyncio.create_subprocess_exec()` is used in place of `subprocess.run()` in all proof/model-finding paths

---

## Phase 4: Correctness Fixes

**Goal:** Mace4 parser, smart routing, group axioms, and syntax validator produce correct output.

**Requirements:** CORR-01, CORR-02, CORR-03, CORR-04

**Plans:**
1. Fix Mace4 `_parse_model()` — structured `predicates`/`functions` dicts; remove duplication loop
2. Fix smart routing in `server.py` — structural quantifier detection via AST parser
3. Fix `group_axioms()` — align identity element `e` with `monoid_axioms()` quantification pattern
4. Improve `syntax_validator.py` — multi-variable quantifiers + scope issue detection

**Success criteria:**
1. `find_model` / `find_counterexample` results have non-empty `predicates` and `functions` fields when a model is found
2. `raw_interpretation` no longer contains duplicate lines
3. Formulas containing `"all_students(x)"` (predicate named `all_...`) route to Prover9, not HCC
4. `group_axioms()` uses consistent identity element treatment with `monoid_axioms()`
5. `check_well_formed("all x y (p(x,y))")` returns valid (no false positive error)
6. `check_well_formed("all x p(x) -> q(x)")` returns a scope warning/error
7. All tests pass after correctness fixes

---

## Phase 5: Cleanup

**Goal:** Codebase is free of dead code, misleading configs, and undocumented tooling.

**Requirements:** CLEAN-01, CLEAN-02, CLEAN-03, CLEAN-04

**Plans:**
1. Add `timeout` param to `Mace4Wrapper.find_model()` and `find_counterexample()`; update MCP tool schema
2. Audit and gitignore `docker-env/`; remove `EXPOSE` ports from Dockerfile
3. Restructure `mcp_logic_agent.md` into proper structured agent documentation

**Success criteria:**
1. `find_model(premises, timeout=30)` respects the timeout in both the Mace4 directive and subprocess call
2. `docker-env/` is in `.gitignore`; Dockerfile has no misleading `EXPOSE` directives
3. `mcp_logic_agent.md` has structured sections: Overview, Tools (with params + examples), Limitations
4. `pytest` and `trunk check` still pass after cleanup

---

## Requirement Coverage

| REQ-ID | Description | Phase |
|---|---|---|
| TEST-01 | Fix test_proofs.py Windows path | 1 |
| TEST-02 | Add assertions to test_enhancements.py | 1 |
| RQ-02 | Configurable log level | 1 |
| TEST-03 | GitHub Actions CI | 2 |
| RQ-01 | Async subprocess (non-blocking) | 3 |
| CORR-01 | Mace4 parser dedup fix | 4 |
| CORR-02 | Smart routing structural detection | 4 |
| CORR-03 | group_axioms() identity consistency | 4 |
| CORR-04 | Syntax validator quantifier scope | 4 |
| CLEAN-01 | Mace4 configurable timeout | 5 |
| CLEAN-02 | docker-env/ gitignore | 5 |
| CLEAN-03 | Remove Dockerfile EXPOSE | 5 |
| CLEAN-04 | Restructure agent docs | 5 |

**Coverage: 13/13 requirements mapped ✓**
