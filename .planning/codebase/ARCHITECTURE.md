---
last_mapped: 2026-05-01
focus: arch
---

# Architecture — mcp-logic

## Overview

`mcp-logic` is a **Model Context Protocol (MCP) server** that exposes 8 logical reasoning tools to AI clients (primarily Claude Desktop). The architecture is a thin integration layer bridging:

1. **External theorem provers** (Prover9, Mace4 — compiled C binaries)
2. **Pure-Python reasoning engines** (HCC propositional prover, VFE abductive engine)

## Architectural Pattern

**Façade + Subprocess Delegation**

```
[MCP Client (Claude)]
         │  stdio JSON-RPC
         ▼
  ┌─────────────────────────────┐
  │     server.py               │
  │  LogicEngine + MCP Server   │  ← Async MCP façade, tool dispatcher
  └──┬───────────┬──────────────┘
     │           │
     ▼           ▼
  [Prover9]  [Mace4]              ← External C binaries via subprocess
  (FOL proof) (model finding)

     │  Also pure-Python engines:
     ▼
  ┌──────────────────────────────────────────────────────┐
  │  hcc_prover.py  →  formula_ast.py                    │
  │  (HCC propositional checker, hypersequent calculus)  │
  └──────────────────────────────────────────────────────┘
  ┌──────────────────────────────────────────────────────┐
  │  vfe_engine.py  →  formula_ast.py + hcc_prover.py    │
  │  (VFE abductive reasoning, Cournot-Gaifman prior)    │
  └──────────────────────────────────────────────────────┘
  ┌──────────────────────────────────────────────────────┐
  │  categorical_helpers.py                              │
  │  (Category theory FOL generation, pure utility)      │
  └──────────────────────────────────────────────────────┘
  ┌──────────────────────────────────────────────────────┐
  │  syntax_validator.py                                 │
  │  (Pre-validation for Prover9/Mace4, regex-based)     │
  └──────────────────────────────────────────────────────┘
```

## Smart Routing (Prove Tool)

The `prove` tool implements smart routing — it inspects the formula set and decides which engine to use:

```python
# From server.py:handle_call_tool("prove")
is_propositional = all("all " not in f and "exists " not in f for f in all_formulas)
if is_propositional:
    # Route to HCC (fast, pure Python, no external call)
    hcc_res = check_contingency(full_formula)
else:
    # Route to Prover9 (subprocess, FOL support)
    result = engine._run_prover(input_file)
```

## Layers

### Layer 1: MCP Server (`server.py`)

- Async entry point (`asyncio.run(main(prover_path))`)
- `LogicEngine` class — owns `prover_exe` path + `Mace4Wrapper` instance
- `@server.list_tools()` — static tool schema registry (8 tools)
- `@server.call_tool()` — synchronous dispatch switch-case over tool name
- `cli()` — argparse CLI entry point, runs `asyncio.run(main(...))`

### Layer 2: Subprocess Wrappers

**`LogicEngine`** (in `server.py`):

- `_create_input_file(premises, goal) -> Path` — writes Prover9-format `.in` temp file
- `_run_prover(input_path, timeout=60) -> Dict` — runs `prover9 -f <path>`, parses stdout

**`Mace4Wrapper`** (`mace4_wrapper.py`):

- `_create_input_file(premises, goal, domain_size) -> Path` — writes Mace4-format `.in` temp file
- `_run_mace4(input_path, timeout=60) -> Dict` — runs `mace4 -f <path>`, parses stdout
- `_parse_model(output: str) -> Dict` — extracts domain size and raw interpretation block
- `find_model(premises, domain_size) -> Dict` — public API
- `find_counterexample(premises, conclusion, domain_size) -> Dict` — public API

### Layer 3: Pure Python Reasoning

**`formula_ast.py`** — Foundation for propositional logic:

- Immutable dataclass AST: `Var`, `Not`, `And`, `Or` (frozen, slotted)
- `Formula = Union[Var, Not, And, Or]` type alias
- Recursive descent parser: `parse(str) -> Formula` with full precedence support
- `to_nnf(Formula) -> Formula` — Negation Normal Form conversion
- Utilities: `complexity()`, `atoms()`, `is_literal()`, `negate()`, `are_complementary()`

**`hcc_prover.py`** — Hypersequent Contingency Calculus:

- Input: propositional formula string
- Process: parse → NNF → hypersequent decomposition (OR/AND rules) → axiomatic check
- Output: `ContingencyResult(is_contingent, is_tautology, is_contradiction, proof_trace, ...)`
- Used by: `vfe_engine.py` (HCC filtering), `server.py` (check_contingency tool + prove routing)

**`vfe_engine.py`** — Variational Free Energy Abductive Reasoning:

- Input: observation string + list of candidate formula strings + max_complexity
- Process: parse candidates → HCC filter (contingency check) → complexity bound → Cournot-Gaifman prior → VFE score (Ω = complexity + KL)
- Output: `AbductionResult(best_explanation, all_candidates, filtered_out_count, message)`

**`categorical_helpers.py`** — Category Theory FOL Generation:

- `CategoricalHelpers.category_axioms()` → 6 FOL strings
- `CategoricalHelpers.functor_axioms(name)` → 2 FOL strings
- `CategoricalHelpers.verify_commutativity(path_a, path_b, start, end)` → `(premises, conclusion)`
- `CategoricalHelpers.natural_transformation_condition(F, G, alpha)` → 1 FOL string
- `monoid_axioms()`, `group_axioms()` — module-level convenience functions

**`syntax_validator.py`** — Pre-flight formula validation:

- `SyntaxValidator.validate(formula)` → `(is_valid, errors, warnings)`
- Checks: balanced parens, quantifier syntax, operator usage, naming conventions
- `validate_formulas(List[str]) -> Dict` — batch validation, used in `prove` tool

## Data Flow: Proof Request

```
Client → prove(premises, conclusion)
  → validate_formulas(premises + [conclusion])      # syntax check
  → if propositional: check_contingency(full_formula) → ContingencyResult
  → else: _create_input_file() → temp .in file
        → subprocess prover9 -f file → stdout
        → parse stdout → {result, proof, ...}
  → JSON TextContent response
```

## Data Flow: Counterexample Request

```
Client → find_counterexample(premises, conclusion, domain_size)
  → Mace4Wrapper._create_input_file(premises, goal=conclusion, domain_size)
      → formulas(goals) block (Mace4 auto-negates internally)
  → subprocess mace4 -f file → stdout
  → parse: "DOMAIN SIZE" + "interpretation(" → model_found
  → enrich result with interpretation message
  → JSON TextContent response
```

## Error Handling Strategy

- **Subprocess errors**: Try/except on `subprocess.TimeoutExpired`, `SubprocessError`, `OSError`, `ValueError` — returns structured `{"result": "error/timeout", "reason": "..."}` dict
- **Tool dispatch errors**: Top-level try/except on `KeyError, ValueError, RuntimeError` — returns `{"error": str(e), "type": ...}`
- **Validation errors**: Early return from `prove` with `{"result": "syntax_error", "validation": ...}`
- **Missing Mace4**: `engine.mace4 = None` if binary not found; tools return `{"error": "Mace4 not available"}`
- **Temp file cleanup**: Always in `finally` block; swallows `FileNotFoundError/PermissionError/OSError`

## Concurrency Model

- Single `asyncio` event loop (MCP stdio server)
- All tool handlers are synchronous (blocking subprocess calls within async context)
- No parallelism, no background tasks, no connection pooling
