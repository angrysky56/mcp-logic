# Plan: from "a prover we call" to a real logic computer

Derived from Harrison, _Handbook of Practical Logic and Automated Reasoning_
(2009), chapters 3–5 and 7. Written for handoff to coding agents: each
package is self-contained, states its dependencies, and ends in a
checkable acceptance test.

## Why this sequence

Today mcp-logic can _run_ solvers. What it cannot do is **reason about its
own answers** — say which of them are decisions and which are guesses,
route a problem to the engine that can actually decide it, or inspect the
structure of a formula it was handed.

Every one of those needs the same missing piece, which is why Package 0
comes first.

## Grounding: what actually exists today

Verified by reading the source, not assumed:

| Component                         | Reality                                                                                                                              |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `formula_ast.py` (411 lines)      | **Propositional only.** `Var`, `Not`, `And`, `Or`, `Implies`, `Iff`. Zero quantifier, predicate or term classes. Feeds `hcc_prover`. |
| `syntax_validator.py` (388 lines) | **String/regex heuristics.** `_check_quantifiers` and `_symbol_arities` approximate structure with patterns; there is no parse tree. |
| `server.py`                       | Prover9 subprocess; now classifies `sos_empty` vs resource-limit exits.                                                              |
| `mace4_wrapper.py`                | Mace4 subprocess; bounded finite-model search.                                                                                       |
| `smt_solver.py`                   | Z3 via SMT-LIB strings. Ground/quantifier-free in practice.                                                                          |
| `logic_advisor.py`                | LLM formalization; routes arithmetic to Z3 by **regex on the question text**.                                                        |

**There is no first-order abstract syntax tree anywhere in the repo.**
Fragment detection, theory-aware routing and free-variable analysis all
need one. Attempting any of them without it produces three incompatible
regex approximations of "what shape is this formula" — which is precisely
the class of bug that cost us the `xyz2` incident.

---

## Package 0 — First-order AST and parser

**Depends on:** nothing. **Blocks:** 1, 2, 3, 4.

### Package 0 Goal

A real parse tree for the Prover9 subset the project already accepts, so
that every later package asks structural questions of a tree instead of a
regex.

### Package 0 Design

New module `src/mcp_logic/fol_ast.py`. Do **not** extend
`formula_ast.py` — it is propositional, is consumed by `hcc_prover`, and
its tests pin that behaviour. Add alongside; consider unifying later.

Node types, mirroring Harrison §3.1:

```text
Term    ::= Var(name) | Fn(name, args)          # Fn with args=[] is a constant
Formula ::= Atom(pred, args) | Equal(l, r)
          | Not | And | Or | Implies | Iff
          | Forall(var, body) | Exists(var, body)
```

Parser accepts the syntax in `syntax_contract.PROVER9_SYNTAX_RULES`:
`all x (...)`, `exists x (...)`, `-> <-> & | -`, `=`, `!=`, lowercase
predicates and functions, nested terms.

Required analyses (each ~10 lines given the tree):

- `free_variables(formula) -> set[str]`
- `bound_variables(formula) -> set[str]`
- `function_symbols(formula) -> dict[str, int]` (name → arity)
- `predicate_symbols(formula) -> dict[str, int]`
- `prenex(formula) -> Formula` (Harrison §3.5)
- `skolemize(formula) -> Formula` (Harrison §3.6) — needed by Package 1

### Constraints

- Pure, no I/O, no solver calls. Must import in under 50 ms.
- Round-trip: `str(parse(s))` must re-parse to an equal tree.
- Parse failure raises a `ParseError` carrying the offending position.

### Package 0 Acceptance

- `parse("all x (human(x) -> mortal(x))")` → `Forall("x", Implies(...))`.
- `free_variables` on the historical hazard
  `all x all y (mult(x,y,xy2) -> ...)` returns `{"xy2"}`.
- Round-trip property test over ≥ 20 formulas drawn from the existing
  test suite and `categorical_helpers`.
- Every formula in `monoid_axioms()` and `group_axioms()` parses.

---

## Package 1 — Decidable fragment detection

**Depends on:** 0. Harrison §5.2, §5.3, §5.5.

### Package 1 Goal

Turn "we found no model up to size 6" into "**there is no model**", where
that is mathematically licensed — and keep hedging where it is not.

### Package 1 Design

New module `src/mcp_logic/fragments.py`.

Detect, on the Skolemized/prenex form:

1. **Bernays–Schönfinkel–Ramsey (AE / `∃*∀*`)** — prefix is existentials
   then universals, **no function symbols of arity ≥ 1** (constants fine).
   Has the finite model property with a _computable_ bound:
   `domain = max(1, #existential vars + #constants)`. A Mace4 search to
   that bound is a **decision procedure**.
2. **Monadic** — every predicate unary, no functions of arity ≥ 1.
   Decidable; finite model bound `2^k` for `k` predicates. Guard against
   the exponential: only claim decidability when `2^k` is under a
   configured cap (suggest 2^10).

API:

```python
@dataclass(frozen=True)
class FragmentVerdict:
    fragment: str          # "bsr" | "monadic" | "unknown"
    decidable: bool
    model_bound: int | None
    reason: str            # plain-English justification for the answer
```

### Wiring

`find_model` and `find_counterexample`: when the premise set is in a
decidable fragment, search to `model_bound` and report
`decided: true` with `no_model_found` meaning **no model exists at all**.
Outside a known fragment, keep the current honest hedge.

### Package 1 Acceptance

- BSR example (`exists x all y (p(x) -> p(y))`) → `decidable=True`.
- A formula with a real function symbol (`all x (p(f(x)))`) → not BSR.
- **Negative control:** the dense-order axioms
  (`all x exists y (lt(x,y))`, transitivity, irreflexivity, density) must
  be reported **not decidable by this route** — they are consistent but
  have no finite model, so a wrong "decided" here is the failure mode
  this package exists to avoid.
- End-to-end: a BSR non-entailment returns `decided: true`.

---

## Package 2 — Unified epistemic status

**Depends on:** 0 (nominally); can proceed in parallel with 1.

### Package 2 Goal

One vocabulary for "how much do we know". Four have accreted
independently and they do not compose:

| Field        | Set by  | Means                         |
| ------------ | ------- | ----------------------------- |
| `verified`   | advisor | a solver returned _something_ |
| `definitive` | `prove` | search saturated              |
| `vacuity`    | Mace4   | model is degenerate           |
| `unknown`    | Z3      | gave up                       |

### Package 2 Design

A single `status` enum on every solver result:

- `PROVED` / `REFUTED` — a decision, with evidence.
- `SATURATED_NO_PROOF` — decided negative by exhaustion.
- `BOUNDED_NO_MODEL` — no model up to bound, **not** a decision unless a
  fragment verdict says otherwise.
- `RESOURCE_LIMIT` — we stopped early; no information.
- `MALFORMED` — the input was rejected.

`verified` becomes derived (`status in {PROVED, REFUTED,
SATURATED_NO_PROOF}` or a fragment-licensed `BOUNDED_NO_MODEL`), not
independently assigned.

### Package 2 Acceptance

- No code path sets `verified` directly.
- `RESOURCE_LIMIT` can never produce a natural-language answer asserting
  the conclusion is false. Test this at the advisor level.
- Existing `verified` semantics preserved for all current tests.

---

## Package 3 — Theory-aware routing (replacing the regex)

**Depends on:** 0, 2. Harrison §5.13 (Nelson–Oppen).

### Package 3 Goal

Handle problems that mix arithmetic with uninterpreted predicates. Today
`looks_arithmetic()` greps the _question text_ and picks one engine;
anything genuinely mixed — "everyone over 18 can vote; Alice is 20; can
Alice vote?" — fails whichever way it is routed.

### Package 3 Design

Route on the parsed **formula**, not the English:

- pure FOL, no arithmetic → Prover9/Mace4
- arithmetic, no uninterpreted symbols → Z3
- **mixed** → Z3, declaring predicates as uninterpreted Bool-valued
  functions and using quantifiers

Do **not** implement Nelson–Oppen. Z3 already implements it; the
engineering job is presenting mixed problems to it correctly. Extend
`smt_solver.build_declarations` to emit `declare-fun` for predicates.

### Package 3 Acceptance

- The voting example returns `proved` end-to-end via `ask_logic_advisor`.
- Existing pure-FOL and pure-arithmetic routing is unchanged (regression).
- `looks_arithmetic` is deleted, not merely bypassed.

---

## Package 4 — Free-variable lint

**Depends on:** 0. Harrison §3.4–3.6.

### Package 4 Goal

Catch the `xyz2` class of hazard at validation time. A free variable in a
Prover9 formula is _implicitly universally quantified_ — sometimes
intended, frequently not, and invisible either way.

### Package 4 Design

`check_well_formed` gains a warning (not an error — implicit
generalization is legal and `categorical_helpers` relied on it):

> `xyz2` is free and will be implicitly universally quantified. If that is
> intended, bind it explicitly with `all xyz2 (...)`.

Also warn on **bound but unused** variables (the `ybc` case).

### Package 4 Acceptance

- The historical relational associativity axiom produces both warnings.
- The current equational axioms produce none.
- `valid` stays `True` — these are warnings, not rejections.

---

## Explicitly out of scope

- **Congruence closure (§4.4).** Z3 decides QF_UF already. Writing our own
  is a study exercise, not a capability gain. Route ground equality to Z3
  instead.
- **Lean integration.** Probed and rejected: the model writes plausible
  Lean but drops hypotheses (it stated "every prime > 2 is odd" as
  `∀ p, p > 2 → p % 2 = 1`, dropping primality — false as written and it
  would still compile). Costs a mathlib toolchain to gain a checker that
  cannot catch that error.
- **Rewriting the relational `category_axioms`.** Composition in a
  category is genuinely partial; the 3-place relation is correct there.
  Only total operations (monoid, group) belong in equational form.
- **Replacing `hcc_prover`.** It works and is fast on propositional input.

## Suggested order

`0 → (1 ‖ 2) → 3 → 4`. Package 0 is the bottleneck and deserves the most
careful review; 1 and 2 are independent of each other; 4 is small and can
be slotted in any time after 0.

## Verification, every package

```bash
cd /home/ty/Repositories/ai_workspace/mcp-logic
.venv/bin/python -m pytest tests/ -q          # full suite
trunk check --no-progress --ci                 # lint, must show no NEW issues
.venv/bin/python tests/manual_advisor_smoke.py # 8/8, needs GPU
```

CI runs **Python 3.10**; the dev venv is 3.13. Check both before claiming
done. The GPU has a broken fan — warn before any run that loads the
advisor model, and keep an eye on `nvidia-smi` (ceiling ~93 °C).
