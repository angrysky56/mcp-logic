# 🧠 MCP-Logic Agent Guide

You are equipped with **mcp-logic**, a high-fidelity formal reasoning engine. It exposes the power of First-Order Logic (FOL) theorem proving, finite model finding, and categorical reasoning to your conversational interface.

---

## 🛠 Core Toolset

### 1. `prove` — Theorem Proving (Prover9)
**Purpose**: Rigorously prove that a conclusion follows from a set of premises.
- **When to use**: To verify the validity of logical arguments, confirm mathematical theorems, or check if specific implications hold.
- **Input Parameters**:
  - `premises` (Array of Strings): FOL formulas representing assumptions.
  - `conclusion` (String): The statement to be proven.
- **Best Practices**:
  - Keep predicates lowercase (e.g., `human(socrates)`).
  - Use explicit quantification: `all x (P(x) -> Q(x))`.
  - Parenthesize complex scopes: `all x (man(x) -> (exists y (father(y,x))))`.

### 2. `find_model` — Consistency & Exploration (Mace4)
**Purpose**: Find a finite model (interpretation) where all premises are TRUE.
- **When to use**: To verify that a set of axioms is consistent, or to explore what kind of structures a theory permits.
- **Input Parameters**:
  - `premises` (Array of Strings): FOL axioms to satisfy.
  - `domain_size` (Integer, Optional): Fixed size of the domain (default: searches 2-10).
  - `timeout` (Integer, Optional): Search timeout in seconds (default: 60).
- **Pro Tip**: If `find_model` returns a model, your axioms are **consistent**.

### 3. `find_counterexample` — Disproving Claims (Mace4)
**Purpose**: Show that a conclusion does NOT follow from premises by finding a "counter-model."
- **When to use**: When `prove` fails, use this to understand *why*. It finds a world where premises are true but the conclusion is false.
- **Input Parameters**:
  - `premises` (Array of Strings): Logical assumptions.
  - `conclusion` (String): The statement to disprove.
  - `domain_size` (Integer, Optional): Domain limit.
  - `timeout` (Integer, Optional): Search timeout in seconds.

### 4. `check_well_formed` — Syntax Guard
**Purpose**: Validate formula syntax and get detailed error/warning feedback.
- **When to use**: BEFORE calling `prove` or `find_model` for complex or user-provided formulas.
- **Validation Features**: Catches unmatched parentheses, invalid characters, and quantifier scope issues.

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
- **Note**: This tool generates the *setup*; you must pass the resulting premises/conclusion to `prove` to finalize the verification.

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
  - *"Is it true that if all humans are mortal and Socrates is human, then Socrates is mortal?"*
  - *"Find a model where there exist at least two distinct elements and every element has a successor."*
  - *"Is the formula (P → Q) ↔ (¬Q → ¬P) a tautology?"*
  - *"Can you disprove that all birds can fly, given that penguins are birds but cannot fly?"*

### Recommended Workflow
- **For natural-language questions**: Call `ask_logic_advisor` — it handles everything.
- **For pre-formalized problems**: Use `prove`, `find_model`, etc. directly when you already have FOL formulas.
- **For debugging**: Pass a failed proof result as `context` to `ask_logic_advisor` and ask "Why did this proof fail?"

---

## ✍️ FOL Syntax Reference

| Name | Symbol | Example |
| :--- | :--- | :--- |
| **Universal** | `all` | `all x (human(x) -> mortal(x))` |
| **Existential** | `exists` | `exists x (prime(x) & even(x))` |
| **Negation** | `-` | `-cold(water)` |
| **Conjunction** | `&` | `P & Q` |
| **Disjunction** | `\|` | `P \| Q` |
| **Implication** | `->` | `P -> Q` |
| **Equivalence** | `<->` | `P <-> Q` |
| **Equality** | `=` | `x = y` |

---

## ⚠️ Important Constraints
- **Studio-Ready Logic**: Always interpret Prover9/Mace4 outputs into plain English for the user. Don't just dump raw logic.
- **Complexity Management**: If a proof is taking too long, break it into **lemmas**. Prove the lemma first, then use it as a premise for the final goal.
- **Lowercase Convention**: Predicates and functions should be lowercase. Constants can be lowercase. Variables are usually `x`, `y`, `z`.
