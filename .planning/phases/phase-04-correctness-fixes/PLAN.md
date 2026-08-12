# Plan — Phase 4: Correctness Fixes

Improve the accuracy and robustness of Mace4 model parsing, tool routing, categorical axioms, and syntax validation.

## Objectives

- **CORR-01**: Fix Mace4 parser to remove duplicate lines and populate structured fields (`predicates`, `functions`).
- **CORR-02**: Implement robust FOL detection for smart routing using structural patterns (quantifiers/predicates).
- **CORR-03**: Align `group_axioms()` identity element `e` with `monoid_axioms()` for consistency.
- **CORR-04**: Support multi-variable quantifiers and detect scope issues in `syntax_validator.py`.

## Proposed Changes

### 1. Mace4 Parser Hardening (`src/mcp_logic/mace4_wrapper.py`)

- Refactor `_parse_model()`:
  - Stop double-appending to `raw_interpretation`.
  - Extract `relation(name, [values...])` into `model["predicates"]`.
  - Extract `function(name, [values...])` into `model["functions"]`.
  - Handle constants (functions with 0 or 1 arg depending on Mace4 output style).

### 2. Smart Routing Refinement (`src/mcp_logic/server.py`)

- Replace the fragile `"all " in f` check with a more robust detection:
  - Quantifiers: `\b(all|exists)\s+\w+` (ensures space after word).
  - Predicates: `\w+\s*\(` (where word is not a quantifier).
  - Variables/Constants: Detection of lowercase words in predicate arguments.
- This ensures formulas like `all_students(x)` are routed correctly (to FOL if they have arguments, or stay propositional if they are just atomic variables).

### 3. Categorical Axioms Consistency (`src/mcp_logic/categorical_helpers.py`)

- Update `monoid_axioms()` and `group_axioms()` to treat `e` as a constant.
- `monoid_axioms()`: Change `exists e (all x ...)` to `all x (mult(e,x,x) & mult(x,e,x))`.
- Ensure `group_axioms()` uses the same `e`.

### 4. Syntax Validator Enhancements (`src/mcp_logic/syntax_validator.py`)

- Update `_check_quantifiers` regex to `\b(all|exists)\s+([\w\s]+?)\s*\(` to support `all x y (p(x,y))`.
- Add a heuristic check for quantifier scope:
  - If `all x (p(x) -> q(x))` is missing outer parentheses, e.g., `all x p(x) -> q(x)`, Prover9 will bind `all x` only to `p(x)`.
  - Warn if an implication or disjunction follows a quantifier without explicit parentheses.

## Verification Plan

### Automated Tests

- Create `tests/test_correctness.py`:
  - `test_mace4_structured_output`: Verify `predicates` and `functions` are populated and `raw_interpretation` is clean.
  - `test_smart_routing`: Test edge cases like `all_students(x)`, `p(x,y)`, and pure propositional `p & q`.
  - `test_group_axioms_consistency`: Verify `group_axioms` follows `monoid_axioms` and proves basic identity properties.
  - `test_validator_multi_variable`: Check `all x y (p(x,y))` passes.
  - `test_validator_scope_warning`: Check `all x p(x) -> q(x)` produces a warning.

### Manual Verification

- Run `find_model` with a simple group theory premise and inspect the JSON output for structure.
- Run `prove` with a formula that previously misrouted.
