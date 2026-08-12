# mcp-logic — Hardening & Correctness

## What This Is

A focused hardening initiative for the `mcp-logic` MCP server. The codebase is functionally working but has a documented set of 13 known issues across runtime quality, testing, correctness, and code cleanliness. This milestone fixes all of them — no new features, only reliability, correctness, and production readiness.

**Core value:** A correctly-behaving, properly-tested, CI-backed MCP logic server that a developer can trust in production.

## Context

- **Type:** Brownfield — existing codebase with 8 working MCP tools
- **Stack:** Python 3.13, MCP SDK, Prover9/Mace4 (LADR binaries), HCC/VFE pure-Python engines
- **Codebase map:** `.planning/codebase/` (STACK, INTEGRATIONS, ARCHITECTURE, STRUCTURE, CONVENTIONS, TESTING, CONCERNS)
- **Users:** AI clients (primarily Claude Desktop) connecting via MCP stdio transport

## Problem

The codebase map identified 13 issues that range from correctness bugs (blocking subprocess in async context, Mace4 parser duplication) to test infrastructure failures (hardcoded Windows paths breaking Linux tests, no assertions in integration tests, no CI pipeline). These prevent confident iteration and production deployment.

## Goal

All 13 issues resolved, verified by a passing test suite and a green CI run.

---

## Requirements

### Validated (existing capabilities — already working)

- ✓ `prove` tool with Prover9 + HCC smart routing — existing
- ✓ `check_well_formed` syntax validation — existing
- ✓ `find_model` via Mace4 — existing
- ✓ `find_counterexample` via Mace4 — existing
- ✓ `verify_commutativity` categorical diagram tool — existing
- ✓ `get_category_axioms` (category/functor/group/monoid/natural-transformation) — existing
- ✓ `check_contingency` HCC propositional checker — existing
- ✓ `abductive_explain` VFE engine — existing
- ✓ Formula AST parser + NNF conversion — existing
- ✓ Trunk linter configuration (ruff, black, bandit, etc.) — existing

### Active (issues to fix — this milestone)

#### Runtime Quality

- [ ] **RQ-01**: Replace blocking `subprocess.run()` in async tool handlers with `asyncio.create_subprocess_exec()` or thread executor to avoid blocking the event loop
- [ ] **RQ-02**: Make log level configurable via `--log-level` CLI arg (default `INFO`, not hardcoded `DEBUG`)

#### Testing

- [ ] **TEST-01**: Fix `test_proofs.py` hardcoded Windows binary path — use a pytest fixture or `skipif` for the correct Linux `ladr/bin/` path
- [ ] **TEST-02**: Add real `assert` statements to `test_enhancements.py` to replace print-only checks
- [ ] **TEST-03**: Add a GitHub Actions CI workflow that installs LADR, runs `pytest`, and runs `trunk check`

#### Correctness

- [ ] **CORR-01**: Fix Mace4 `_parse_model()` duplicate data bug — properly parse `function()`/`relation()` entries into structured `predicates`/`functions` dicts instead of duplicating into `raw_interpretation`
- [ ] **CORR-02**: Fix smart-routing heuristic in `server.py` — use the formula AST parser or syntax validator to detect quantifiers structurally instead of fragile string matching
- [ ] **CORR-03**: Fix `group_axioms()` inconsistency — align identity element `e` treatment with `monoid_axioms()` pattern
- [ ] **CORR-04**: Improve `syntax_validator.py` quantifier scope detection — handle multi-variable quantifiers and detect missing scope issues

#### Cleanup

- [ ] **CLEAN-01**: Make Mace4 timeout configurable — accept `timeout` param in `find_model()` / `find_counterexample()`
- [ ] **CLEAN-02**: Remove or document `docker-env/` venv; add to `.gitignore` if unused
- [ ] **CLEAN-03**: Remove misleading `EXPOSE 8888-8892` from Dockerfile (MCP uses stdio, not TCP)
- [ ] **CLEAN-04**: Restructure `mcp_logic_agent.md` into proper structured documentation

### Out of Scope

- New MCP tools or reasoning modes — next milestone
- Performance benchmarking — not a current concern
- Multi-client / concurrent session support — MCP stdio is inherently single-session
- Full FOL parser rewrite — scoped improvement to syntax validator only

---

## Key Decisions

| Decision                                             | Rationale                                                     | Outcome   |
| ---------------------------------------------------- | ------------------------------------------------------------- | --------- |
| Fix all 13 issues in one milestone                   | They're inter-related; partial fixes leave a fragile codebase | — Pending |
| Use `asyncio.create_subprocess_exec()` for async fix | Native async; no thread pool overhead                         | — Pending |
| Add CI before fixing tests                           | CI gate makes test fixes verifiable                           | — Pending |
| No new features                                      | Stability first; clean foundation before extending            | — Active  |

---

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition:**

1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions

**After milestone completion:**

1. Full review of all sections
2. Core Value check — still the right priority?
3. Update Context with current state

---

Last updated: 2026-05-01 after initialization.
