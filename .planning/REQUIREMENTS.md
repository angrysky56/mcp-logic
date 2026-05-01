# Requirements — mcp-logic Hardening

## v1 Requirements

### Runtime Quality

- [ ] **RQ-01**: Replace blocking `subprocess.run()` in async tool handlers (`server.py:handle_call_tool`) with `asyncio.create_subprocess_exec()` to avoid blocking the event loop during 60-second proof searches
- [ ] **RQ-02**: Make log level configurable via `--log-level` CLI argument (default `INFO`); remove hardcoded `logging.basicConfig(level=logging.DEBUG)`

### Testing

- [ ] **TEST-01**: Fix `test_proofs.py` hardcoded Windows binary path (`F:/Prover9-Mace4/bin-win32`) — use a pytest fixture or `skipif` guard resolving the correct `ladr/bin/` path on Linux
- [ ] **TEST-02**: Add real `assert` statements to `test_enhancements.py` — replace all print-only checks with assertions that verify `result["result"]` values and key fields
- [ ] **TEST-03**: Add GitHub Actions CI workflow (`.github/workflows/ci.yml`) that: installs LADR build deps, builds `prover9`/`mace4`, runs `pytest tests/`, and runs `trunk check`

### Correctness

- [ ] **CORR-01**: Fix Mace4 `_parse_model()` duplicate data bug — parse `function()`/`relation()` entries into structured `predicates`/`functions` dicts; remove the loop that re-appends already-captured lines into `raw_interpretation`
- [ ] **CORR-02**: Fix smart-routing heuristic in `server.py` — replace fragile `"all " not in f` string matching with structural quantifier detection using the formula AST parser or syntax validator
- [ ] **CORR-03**: Fix `group_axioms()` in `categorical_helpers.py` — align identity element `e` quantification with the `monoid_axioms()` pattern for consistency
- [ ] **CORR-04**: Improve `syntax_validator.py` quantifier scope detection — support multi-variable quantifiers (`all x y (...)`) and detect missing scope issues like `all x p(x) -> q(x)`

### Cleanup

- [ ] **CLEAN-01**: Make Mace4 timeout configurable — accept optional `timeout: int` param in `find_model()` and `find_counterexample()`, threading it to both the `assign(max_seconds,...)` directive and `subprocess.run(..., timeout=...)`
- [ ] **CLEAN-02**: Confirm `docker-env/` venv is unused; add to `.gitignore`
- [ ] **CLEAN-03**: Remove misleading `EXPOSE 8888 8889 8890 8891 8892` from `Dockerfile` — MCP uses stdio transport, not TCP
- [ ] **CLEAN-04**: Restructure `mcp_logic_agent.md` into proper structured agent documentation (tool descriptions, parameter examples, usage patterns)

---

## v2 Requirements (Deferred)

- New MCP tools or reasoning modes
- Full FOL quantifier parser (beyond scoped syntax validator improvements)
- Multi-client / concurrent session support
- Performance benchmarking suite
- Containerized deployment workflow

---

## Out of Scope

- New features — this milestone is hardening only
- Rewriting the formula AST parser from scratch — improvement in scope, not replacement
- HTTP/REST transport — MCP stdio is the protocol
- Authentication — out of MCP's scope at this layer

---

## Traceability

| REQ-ID   | Phase | Plan |
| -------- | ----- | ---- |
| TEST-01  | 1     | —    |
| TEST-02  | 1     | —    |
| RQ-02    | 1     | —    |
| TEST-03  | 2     | —    |
| RQ-01    | 3     | —    |
| CORR-01  | 4     | —    |
| CORR-02  | 4     | —    |
| CORR-03  | 4     | —    |
| CORR-04  | 4     | —    |
| CLEAN-01 | 5     | —    |
| CLEAN-02 | 5     | —    |
| CLEAN-03 | 5     | —    |
| CLEAN-04 | 5     | —    |
