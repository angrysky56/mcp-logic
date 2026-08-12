# 🧠 MCP-Logic Agent Guide

You are equipped with **mcp-logic**, a high-fidelity formal reasoning engine. It exposes the power of First-Order Logic (FOL) theorem proving, finite model finding, SMT arithmetic, and categorical reasoning to your conversational interface.

## ⚡ Pick the right engine first

| The question involves…                                           | Use                                           | Why                                                  |
| ---------------------------------------------------------------- | --------------------------------------------- | ---------------------------------------------------- |
| Quantifiers, predicates, relations                               | `prove` / `find_model` (Prover9/Mace4)        | Full first-order reasoning                           |
| **Numbers of any kind**                                          | `prove_arithmetic` / `check_satisfiable` (Z3) | **Prover9 has NO arithmetic** and will fail or stall |
| Plain propositional formulas                                     | `check_contingency`                           | Instant, no search                                   |
| A natural-language question you don't want to formalize yourself | `ask_logic_advisor`                           | Onboard LLM formalizes, solves and explains          |

Getting this wrong is the most common failure: sending `x + 1 > x` to
Prover9 produces a syntax error or an endless search, never an answer.

## ⚠️ Trust the `verified` flag

`ask_logic_advisor` returns `verified: true/false`. **False means no solver
verdict was obtained** — the answer is not machine-checked and must never be
presented as a proof. A `warning` field accompanies it.

---

## 🛠 Core Toolset

### 1. `prove` — Theorem Proving (Prover9)

**Purpose**: Rigorously prove that a conclusion follows from a set of premises.

- **When to use**: To verify the validity of logical arguments, confirm mathematical theorems, or check if specific implications hold.
- **Input Parameters**:
  - `premises` (Array of Strings): FOL formulas representing assumptions.
  - `conclusion` (String): The statement to be proven.
- **Syntax rules** (shared verbatim with the onboard advisor — edit them in
  `src/mcp_logic/syntax_contract.py`, then run
  `python -m mcp_logic.syntax_contract --sync`):

<!-- BEGIN GENERATED: prover9-syntax -->

- ASCII only. Never use Unicode logic symbols.
- Universal: all x (human(x) -> mortal(x))
- Existential: exists x (pet(x) & dog(x))
- Connectives: -> implies, <-> iff, & and, | or, - not
- Predicates, functions and constants are lowercase: human(x), socrates
- Variables are lowercase letters: x, y, z
- Equality =, inequality !=
- Quantifiers MUST be parenthesized, and scope explicitly:
  all x (man(x) -> (exists y (father(y, x))))
- No trailing period on a formula.
- A predicate must take the SAME number of arguments everywhere it appears.

<!-- END GENERATED: prover9-syntax -->

### 2. `find_model` — Consistency & Exploration (Mace4)

**Purpose**: Find a finite model (interpretation) where all premises are TRUE.

- **When to use**: To verify that a set of axioms is consistent, or to explore what kind of structures a theory permits.
- **Input Parameters**:
  - `premises` (Array of Strings): FOL axioms to satisfy.
  - `domain_size` (Integer, Optional): Fixed size of the domain. Omit it to
    enable automatic complete search for recognized decidable fragments.
  - `timeout` (Integer, Optional): Search timeout in seconds (default: 60).
- **Decision metadata**: `decided: true` means the tool completed a licensed
  finite-model decision procedure for the reported `fragment` and
  `model_bound`. In that case, `no_model_found` means no model exists at all.
  When `decided` is false, it means only that the configured finite search
  found none.
- **Pro Tip**: If `find_model` returns a model, your axioms are **consistent**.

### 3. `find_counterexample` — Disproving Claims (Mace4)

**Purpose**: Show that a conclusion does NOT follow from premises by finding a "counter-model."

- **When to use**: When `prove` fails, use this to understand _why_. It finds a world where premises are true but the conclusion is false.
- **Input Parameters**:
  - `premises` (Array of Strings): Logical assumptions.
  - `conclusion` (String): The statement to disprove.
  - `domain_size` (Integer, Optional): Domain limit.
  - `timeout` (Integer, Optional): Search timeout in seconds.
- **Decision metadata**: With `decided: true`, `no_model_found` establishes
  that no counterexample exists; otherwise it remains a bounded-search result.

### 4. `check_well_formed` — Syntax Guard

**Purpose**: Validate formula syntax and get detailed error/warning feedback.

- **When to use**: BEFORE calling `prove` or `find_model` for complex or user-provided formulas.
- **Validation Features**: Catches unmatched parentheses, invalid characters, and quantifier scope issues.

### 4b. `prove_arithmetic` — Numbers (Z3 SMT)

**Purpose**: Prove or refute a claim involving **arithmetic**.

- **When to use**: ANY time numbers are involved. Prover9 has no theory of
  arithmetic — it cannot decide that `2 + 2 = 4` or that `x + 1 > x`. Reach
  for this instead of `prove` the moment integers, reals, or comparisons
  appear.
- **Syntax**: SMT-LIB **prefix** notation, not Prover9. `(> x 0)`,
  `(= y (+ x 1))`, `(=> a b)`. Declare every variable:
  `variables={"x": "Int"}` (sorts: `Int`, `Real`, `Bool`).
- **Returns**: `proved`, or `counterexample` with concrete values that break
  the claim, or `unknown` when Z3 cannot decide (common for nonlinear
  arithmetic and quantifiers) — `unknown` is not a "no".

### 4c. `check_satisfiable` — Numeric Consistency (Z3 SMT)

**Purpose**: Can these arithmetic constraints all hold at once? Returns a
concrete satisfying assignment.

- **When to use**: Consistency checks, puzzles, scheduling, "is there an n
  such that…" questions over numbers.
- **Example**: `constraints=['(> n 0)', '(< n 10)', '(= (mod n 3) 0)']`,
  `variables={'n': 'Int'}` → satisfiable, `n = 3`.

### 5. `check_contingency` — Propositional Fast-Path (HCC)

**Purpose**: Instantly check if a propositional formula is a tautology, contradiction, or contingent.

- **When to use**: For simple boolean logic (P, Q, R) where FOL power is overkill. Uses the Hypersequent Contingency Calculus.

### 6. `abductive_explain` — Inference to the Best Explanation (VFE)

**Purpose**: Select the "best" explanation for an observation from a list of candidates.

- **How it works**: Uses Variational Free Energy (VFE) scoring. It balances explanatory power (low surprisal) with syntactic simplicity (low complexity/Ockham's Razor).

---

## 📐 Categorical Reasoning Utilities

### 7. `get_category_axioms` — Structural Foundations

**Purpose**: Retrieve pre-defined FOL axioms for standard mathematical structures.

- **Supported Concepts**: `category`, `functor`, `natural-transformation`, `monoid`, `group`.

### 8. `verify_commutativity` — Diagram Verification

**Purpose**: Map path equality in a categorical diagram to a FOL proof problem.

- **Input**: `path_a`, `path_b` (Arrays of morphism names), `object_start`, `object_end`.
- **Note**: This tool generates the _setup_; you must pass the resulting premises/conclusion to `prove` to finalize the verification.

---

## 🚀 Advanced Workflows

### The "Failure Recovery" Loop

1. **Try `prove(premises, conclusion)`**.
2. **If search fails**: Call `find_counterexample(premises, conclusion)`.
3. **If counterexample found**: Explain the specific model to the user (e.g., "In this world, Tweety is a bird but cannot fly...").
4. **If no counterexample found**: Suggest increasing the `timeout` or `domain_size`.

### Categorical Proofs

1. Call `get_category_axioms("category")`.
2. Add specific definition (e.g., `morphism(f)`, `compose(f, id, f)`).
3. Call `prove(...)` to verify properties like identity laws or associativity.

---

## 🤖 Onboard Logic Advisor (TwIL-LM3)

### 9. `ask_logic_advisor` — Natural Language → Complete Solution

**Purpose**: Solve a logic problem end-to-end without manually writing FOL formulas.

- **What it does**: You pose a question in natural language, and the onboard reasoning LLM (TwIL-LM3, 3B params) automatically:
  1. **Formalizes** your question into Prover9/Mace4 syntax
  2. **Runs** the appropriate solver (prove, find_model, find_counterexample, etc.)
  3. **Interprets** the result in plain English
- **When to use**: When you're unsure about FOL syntax, want to quickly test an argument, or need to translate natural language into formal logic.
- **Input Parameters**:
  - `question` (String): Your logic question in plain English.
  - `context` (String, Optional): Background knowledge, constraints, or a previous result to debug.
- **Examples**:
  - _"Is it true that if all humans are mortal and Socrates is human, then Socrates is mortal?"_
  - _"Find a model where there exist at least two distinct elements and every element has a successor."_
  - _"Is the formula (P → Q) ↔ (¬Q → ¬P) a tautology?"_
  - _"Can you disprove that all birds can fly, given that penguins are birds but cannot fly?"_

### Recommended Workflow

- **For natural-language questions**: Call `ask_logic_advisor` — it handles everything.
- **For pre-formalized problems**: Use `prove`, `find_model`, etc. directly when you already have FOL formulas.
- **For debugging**: Pass a failed proof result as `context` to `ask_logic_advisor` and ask "Why did this proof fail?"

---

## ✍️ FOL Syntax Reference

| Name            | Symbol   | Example                         |
| :-------------- | :------- | :------------------------------ |
| **Universal**   | `all`    | `all x (human(x) -> mortal(x))` |
| **Existential** | `exists` | `exists x (prime(x) & even(x))` |
| **Negation**    | `-`      | `-cold(water)`                  |
| **Conjunction** | `&`      | `P & Q`                         |
| **Disjunction** | `\|`     | `P \| Q`                        |
| **Implication** | `->`     | `P -> Q`                        |
| **Equivalence** | `<->`    | `P <-> Q`                       |
| **Equality**    | `=`      | `x = y`                         |

---

## ⚠️ Important Constraints

- **Studio-Ready Logic**: Always interpret Prover9/Mace4 outputs into plain English for the user. Don't just dump raw logic.
- **Complexity Management**: If a proof is taking too long, break it into **lemmas**. Prove the lemma first, then use it as a premise for the final goal.
- **Lowercase Convention**: Predicates and functions should be lowercase. Constants can be lowercase. Variables are usually `x`, `y`, `z`.
