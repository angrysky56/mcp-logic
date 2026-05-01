---
last_mapped: 2026-05-01
focus: concerns
---

# Concerns — mcp-logic

## High-Priority Issues

### 1. Blocking Subprocess in Async Context

**File**: `src/mcp_logic/server.py:handle_call_tool()` (lines 324-560)

The MCP tool handlers are `async def` but all subprocess calls (`prover9`, `mace4`) are synchronous `subprocess.run()`. This blocks the entire asyncio event loop during 60-second proof searches.

```python
# PROBLEM: This blocks the event loop
result = subprocess.run([str(self.prover_exe), "-f", str(input_path)], ...)
```

**Impact**: Any concurrent MCP requests will stall. Could cause client timeouts.
**Fix**: Use `asyncio.create_subprocess_exec()` or `loop.run_in_executor()` for subprocess calls.

---

### 2. Always-DEBUG Logging Level

**File**: `src/mcp_logic/server.py` line 35

```python
logging.basicConfig(level=logging.DEBUG)
```

This is hardcoded `DEBUG`. In production, this will write every Prover9/Mace4 stdout dump to stderr, which pollutes the MCP stdio transport. Since MCP uses stdin/stdout, logging goes to stderr — but the volume at DEBUG is very high.

**Impact**: Performance degradation, possible client confusion from stderr noise.
**Fix**: Make configurable via `--log-level` CLI arg, default to `INFO`.

---

### 3. Hardcoded Windows Path in `test_proofs.py`

**File**: `tests/test_proofs.py` lines 7, 19, 39

```python
engine = LogicEngine("F:/Prover9-Mace4/bin-win32")
```

These tests are non-functional on Linux/macOS. Since the project uses `ladr/bin/` for the actual binary, these tests should be skipped or parameterized with pytest fixtures.

**Impact**: `pytest tests/` will fail on 3 tests on any non-Windows system.
**Fix**: Use `pytest.mark.skipif` or a shared fixture that resolves the correct binary path.

---

### 4. No CI Pipeline

**Missing**: `.github/workflows/` directory does not exist.

There is no automated testing on push or pull request. The linting toolchain (Trunk) is configured but not automated.

**Impact**: Regressions can go undetected; no quality gate before merging.
**Fix**: Add a GitHub Actions workflow that: (1) installs LADR, (2) runs `pytest`, (3) runs `trunk check`.

---

### 5. `test_enhancements.py` Has No Assertions

**File**: `tests/test_enhancements.py`

All test functions use `print()` statements and conditional `print("✓ ...")` but no `assert` statements. These tests can't catch regressions.

**Impact**: False confidence from green test runs.
**Fix**: Convert print checks to `assert result["result"] == "model_found"` etc.

---

## Medium-Priority Issues

### 6. Model Parser is Incomplete

**File**: `src/mcp_logic/mace4_wrapper.py:_parse_model()` (lines 168-210)

The model parser captures the raw interpretation block but doesn't fully parse `function()` and `relation()` entries into structured data. The loop at line 204 appends already-included data a second time:

```python
# BUG: model["raw_interpretation"] already contains these lines
for line in interpretation.split("\n"):
    if line.startswith("function(") or line.startswith("relation("):
        model["raw_interpretation"] += f"\n{line}"  # DUPLICATES content
```

**Impact**: Duplicate data in `raw_interpretation`; `predicates` and `functions` dicts are always empty.
**Fix**: Properly parse function/relation entries into `model["predicates"]` and `model["functions"]`.

---

### 7. Mace4 Timeout is Independent of Domain Size

**File**: `src/mcp_logic/mace4_wrapper.py` lines 67, 94

The `assign(max_seconds, 60).` directive and the `subprocess.run(..., timeout=60)` are both hardcoded at 60s. For large domain searches, this is very tight; for small domain searches, it may be excessive.

**Impact**: No flexibility for callers who might want faster/slower searches.
**Fix**: Accept a `timeout` parameter in `find_model()` / `find_counterexample()` and thread it through.

---

### 8. Syntax Validator Doesn't Understand FOL Quantifier Scoping Fully

**File**: `src/mcp_logic/syntax_validator.py:_check_quantifiers()` (lines 70-93)

The validator requires every quantifier to be followed by `(`, but this is too strict — `all x (all y (p(x,y)))` is valid, as is deeper nesting. Meanwhile, it doesn't catch missing scope issues like `all x p(x) -> q(x)` (should be `all x (p(x) -> q(x))`).

The regex `r"\b{quantifier}\s+(\w+)"` misses multi-variable quantifiers like `all x y (p(x,y))`.

**Impact**: False positives on valid formulas; misses real scope bugs.
**Fix**: More thorough syntactic analysis or delegate to Prover9's own parser.

---

### 9. Smart Routing Heuristic is Fragile

**File**: `src/mcp_logic/server.py` lines 347-349

```python
is_propositional = all("all " not in f and "exists " not in f for f in all_formulas)
```

String matching (`"all "` contains trailing space) is a fragile heuristic. It will misclassify formulas containing `"all"` as a predicate name (e.g., `all_students(x)`) or will route `"exists"` as a non-propositional marker even in variable names like `exists_path(x)`.

**Impact**: Wrong engine selection → incorrect results without error.
**Fix**: Use the existing `formula_ast.py` parser or `syntax_validator.py` to detect quantifiers structurally.

---

### 10. Two Separate Virtual Environments

**Files**: `.venv/` (Python 3.13), `docker-env/` (Python 3.12)

There are two separate virtual environments in the repo root. `docker-env/` appears to be a legacy Docker-related venv. Both are large and not in `.gitignore` for this project (though the LADR `.gitignore` exists separately).

**Impact**: Disk bloat, confusion about which venv to use.
**Fix**: Confirm `docker-env/` is unused and add it to `.gitignore`.

---

## Low-Priority / Design Notes

### 11. `categorical_helpers.py:group_axioms()` Has a Bug

**File**: `src/mcp_logic/categorical_helpers.py` line 177

```python
"all x exists y (mult(x,y,e) & mult(y,x,e))"
```

The identity element `e` is used as a free constant here (not quantified). This is technically valid in Prover9 (treats `e` as a constant), but it's inconsistent — `monoid_axioms()` uses `exists e (...)`. The group inverse axiom's `e` should refer to the same identity but the connection is implicit and fragile.

---

### 12. Docker Image Exposes Ports That MCP Doesn't Use

**File**: `Dockerfile` line 43

```dockerfile
EXPOSE 8888 8889 8890 8891 8892
```

MCP uses stdio transport, not TCP ports. These `EXPOSE` directives are misleading and likely leftover from an earlier HTTP-based design concept.

---

### 13. `mcp_logic_agent.md` Format is Ad-Hoc

**File**: `mcp_logic_agent.md`

Contains informal agent instructions. As the tool suite grows, this should be maintained as structured documentation rather than a free-form markdown.

---

## Security Notes

- **No authentication**: MCP stdio transport has no auth — any client connected to the process can invoke all tools.
- **Subprocess injection risk**: Premises/conclusions are written to temp files and passed to external binaries. The content is not sanitized for shell injection, but since the binaries are called with `[str(exe), "-f", str(path)]` (not `shell=True`), direct shell injection is prevented.
- **Temp file leakage**: Temp files are created with `tempfile.mkstemp()` (secure) and cleaned up in `finally` blocks. Very low risk.
- **Bandit findings**: Trunk/bandit annotations suggest some false-positive B105 findings on string token constants in `formula_ast.py` (documented and suppressed).
