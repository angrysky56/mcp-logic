---
last_mapped: 2026-05-01
focus: quality
---

# Testing — mcp-logic

## Framework & Configuration

- **Framework**: `pytest`
- **Config**: `pyproject.toml` → `[tool.pytest.ini_options]` with `testpaths = ["tests"]`
- **Activation**: `source .venv/bin/activate && pytest tests/ -v`
- **No CI pipeline**: No `.github/workflows/` — testing is manual only

## Test Files

| File | Lines | Type | Dependencies |
|---|---|---|---|
| `tests/test_hcc_prover.py` | 152 | Unit | `mcp_logic.hcc_prover` only |
| `tests/test_vfe_engine.py` | 97 | Unit | `mcp_logic.vfe_engine` only |
| `tests/test_formula_ast.py` | ? | Unit | `mcp_logic.formula_ast` only |
| `tests/test_enhancements.py` | 110 | Integration (no-assert) | `mace4_wrapper`, `syntax_validator`, `categorical_helpers` |
| `tests/test_proofs.py` | 48 | Integration (Prover9-dependent) | `mcp_logic.server.LogicEngine` |
| `tests/test_debug.py` | ? | Debug helpers | TBD |
| `tests/debug_mace4.py` | ? | Manual script | `Mace4Wrapper` |

## Test Coverage

### Well-Covered (Unit-tested)

**HCC Prover** (`test_hcc_prover.py`) — ~20 test cases:
- Simple contingent formulas: `p`, `p & q`, `p | q`, `~p`
- Tautology detection: `p | ~p`, `(p & q) | (~p | ~q)`, `(p | ~p) & (q | ~q)`
- Contradiction detection: `p & ~p`, `(p | q) & (~p & ~q)`
- Complex contingency: `(p | q) & ~p`, `((p & (q | r)) & (r | q)) | p`
- Proof trace generation and formatting
- Condition A and Condition B failing cases

**VFE Engine** (`test_vfe_engine.py`) — ~8 test cases:
- Basic abduction with tautology filtering
- Complexity bias (simpler explanations win)
- HCC filtering of contradictions
- Max complexity bounds
- Prior probability normalization
- VFE score calculation
- Empty candidates
- Invalid syntax in candidates

### Lightly Covered

**Integration tests** (`test_enhancements.py`) — No assertions, print-only:
- Mace4 model finding: `find_model(["P(a)"], domain_size=2)` and `find_counterexample(["P(a)"], "P(b)", domain_size=2)`
- Syntax validator: valid formula, unbalanced parens
- Categorical helpers: axiom count, commutativity diagram

**Integration tests** (`test_proofs.py`) — Prover9-dependent (hardcoded Windows path):
- `test_socrates_mortality()` — basic syllogism
- `test_complex_proof()` — multi-premise FOL proof
- `test_syntax_validation()` — expects error on invalid input
- **These will FAIL on Linux** (hardcoded path `F:/Prover9-Mace4/bin-win32`)

### Not Covered

- `server.py` (MCP handler logic) — no unit tests for tool dispatch
- `categorical_helpers.py` — no dedicated test file (only tested via `test_enhancements.py` without assertions)
- `syntax_validator.py` — no dedicated test file
- `mace4_wrapper.py` — no assertion-based tests (only `test_enhancements.py` prints)
- End-to-end MCP server tests

## Mocking Strategy

- **No mocking** anywhere in the test suite
- Tests that require Prover9/Mace4 binaries call them directly
- Pure-Python tests (HCC, VFE, formula_ast) need no mocking

## Test Patterns

### Dataclass result assertion (HCC tests)

```python
def test_tautology_simple(self) -> None:
    res = check_contingency("p | ~p")
    assert res.is_contingent is False
    assert res.is_tautology is True
    assert res.is_contradiction is False
```

### Filter count assertion (VFE tests)

```python
def test_basic_abduction(self) -> None:
    res = abductive_explain("raining", ["p", "p & q", "p | ~p"])
    assert res.best_explanation is not None
    assert res.best_explanation.formula_str == "p"
    assert res.filtered_out_count == 1  # p | ~p filtered out
```

### Numeric tolerance (VFE tests)

```python
total_p = sum(c.prior for c in res.all_candidates)
assert pytest.approx(total_p) == 1.0
```

### Print-based integration (test_enhancements.py)

```python
def test_mace4():
    result = mace4.find_model(["P(a)"], domain_size=2)
    print(f"Result: {result['result']}")
    if result["result"] == "model_found":
        print("✓ Model finding works!")
```

## Known Test Issues

1. **`test_proofs.py` hardcodes Windows path** (`F:/Prover9-Mace4/bin-win32`) — will fail on Linux unless path is updated
2. **`test_enhancements.py` has no assertions** — purely observational, won't catch regressions
3. **No CI** — tests are never automatically run on push/PR
4. **Paper Example 3 skipped** (`test_complex_cross_clause_consistency`) — intentionally `pass`'d due to ambiguity in the HCC paper
5. **`test_empty_hyperclause`** — also intentionally `pass`'d

## Running Tests

```bash
# All tests (excluding Prover9-dependent):
cd /home/ty/Repositories/ai_workspace/mcp-logic
source .venv/bin/activate
pytest tests/test_hcc_prover.py tests/test_vfe_engine.py tests/test_formula_ast.py -v

# Full test suite (requires Prover9/Mace4):
pytest tests/ -v

# Integration component test (manual, no assertions):
python tests/test_enhancements.py
```
