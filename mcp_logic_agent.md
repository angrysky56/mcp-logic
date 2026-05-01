# MCP-Logic Agent Instructions

## Overview

You have access to **mcp-logic**, a formal reasoning server that provides automated theorem proving (Prover9), model finding (Mace4), categorical reasoning utilities, and abductive inference. Use these tools to verify logical arguments, find counterexamples, and work with category theory.

## Available Tools

### 1. `prove` - Theorem Proving

**Purpose:** Prove that a conclusion logically follows from premises.

**When to use:**

- Verify logical arguments are valid
- Check if implications hold
- Prove mathematical theorems in first-order logic

**Input:**

```json
{
  "premises": ["all x (P(x) -> Q(x))", "P(a)"],
  "conclusion": "Q(a)"
}
```

**Best Practices:**

- **Pre-validate syntax** with `check_well_formed` first for complex formulas
- Use universal quantifiers (`all x`) for general statements
- Use existential quantifiers (`exists y`) for specific claims
- Keep predicates lowercase: `man(x)` not `Man(x)`
- Add spaces around operators: `P(x) -> Q(x)` not `P(x)->Q(x)`

**Example workflow:**

```
User: "Does 'all humans are mortal' and 'Socrates is human' imply Socrates is mortal?"

1. Translate to FOL:
   - premises: ["all x (human(x) -> mortal(x))", "human(socrates)"]
   - conclusion: "mortal(socrates)"
2. Use prove tool
3. Interpret result: "proved" = valid argument
```

---

### 2. `check_well_formed` - Syntax Validation

**Purpose:** Validate logical formula syntax before attempting proofs.

**When to use:**

- Before complex proofs to catch syntax errors early
- When user provides formulas you're unsure about
- To get helpful suggestions for malformed input

**Returns:**

- `valid: true/false`
- **Errors:** Specific issues with positions (e.g., "Unmatched parenthesis at position 15")
- **Warnings:** Style suggestions (e.g., "Use lowercase for predicates")

**Pro tip:** Always check syntax first for user-provided formulas to give immediate, helpful feedback.

---

### 3. `find_model` - Model Finding

**Purpose:** Find a finite model that satisfies given premises.

**When to use:**

- Explore what a set of axioms actually allows
- Understand the structure of a logical theory
- Verify consistency of axioms (if model found, axioms are consistent)

**Input:**

```json
{
  "premises": ["all x (P(x) -> Q(x))", "P(a)"],
  "domain_size": 2 // optional: specific size, or omit to search 2-10
}
```

**Example use case:**

```
User: "What does group theory with 2 elements look like?"

1. Get group axioms: use get_category_axioms with concept="group"
2. Use find_model with domain_size=2
3. Interpret the model to show the group structure
```

---

### 4. `find_counterexample` - Counterexample Finding ⭐

**Purpose:** Prove a statement is NOT a valid inference by finding a counterexample.

**When to use:**

- Proof attempt failed - understand WHY
- User claims an argument is invalid - show them a counterexample
- Verify that a statement doesn't follow from premises

**How it works:**

- Searches for a model where premises are TRUE but conclusion is FALSE
- If found: conclusion doesn't follow (invalid argument)
- If not found: doesn't prove validity (use `prove` for that)

**Critical insight:**

```
prove() fails → try find_counterexample()
  - If counterexample found: conclusion genuinely doesn't follow
  - If no counterexample: might be provable with different strategy or larger domain
```

**Example workflow:**

```
User: "Does P(a) imply P(b)?"

1. Try prove: premises=["P(a)"], conclusion="P(b)"
2. Result: unprovable
3. Use find_counterexample to show why:
   - Returns model where P(a)=true, P(b)=false
4. Explain: "No, because P(a) says nothing about b"
```

---

### 5. `verify_commutativity` - Categorical Diagrams

**Purpose:** Verify that two paths through a categorical diagram yield the same result.

**When to use:**

- Working with category theory
- Verifying functor properties
- Checking diagram commutativity

**Input:**

```json
{
  "path_a": ["f", "g"], // morphisms in first path
  "path_b": ["h"], // morphisms in second path
  "object_start": "A",
  "object_end": "C",
  "with_category_axioms": true // include category axioms
}
```

**Returns:**

- **premises:** FOL statements (including category axioms if requested)
- **conclusion:** Equality of composed paths (e.g., "comp_a = h")
- **note:** "Use prove tool to verify"

**Workflow:**

```
User: "Verify that f∘g = h in this diagram"

1. Use verify_commutativity to generate FOL
2. Use prove with returned premises and conclusion
3. If proved: diagram commutes ✓
4. If not: use find_counterexample to show a category where it fails
```

---

### 6. `get_category_axioms` - Theory Axioms

**Purpose:** Retrieve FOL axioms for mathematical structures.

**Available concepts:**

- `"category"` - Basic category theory (identity, composition, associativity)
- `"functor"` - Functor preservation properties
- `"natural-transformation"` - Naturality condition
- `"monoid"` - Monoid axioms
- `"group"` - Group axioms

**When to use:**

- Starting a category theory proof
- Need standard axioms for algebraic structures
- Building up complex proofs from foundations

**Example:**

```json
{
  "concept": "functor",
  "functor_name": "F" // optional: default is "F"
}
```

**Workflow for proving functor properties:**

```
1. Get category axioms: get_category_axioms("category")
2. Get functor axioms: get_category_axioms("functor", functor_name="F")
3. Add specific functor definition
4. Use prove to verify property
```

---

### 7. `check_contingency` - Propositional Contingency

**Purpose:** Check if a classical propositional formula is truth-functionally contingent using the Hypersequent Contingency Calculus (HCC).

**When to use:**

- Analyze propositional logic formulas without infinite search spaces.
- Quickly determine if a formula is a tautology, contradiction, or contingent.

**Input:**

```json
{
  "formula": "(P -> Q) | (Q -> P)"
}
```

**Returns:**

- `is_contingent: true/false`
- `is_tautology: true/false`
- `is_contradiction: true/false`
- Proof trace summary.

---

### 8. `abductive_explain` - Abductive Reasoning (VFE Engine)

**Purpose:** Find the best explanation for an observation from a list of candidate hypotheses, using Variational Free Energy (VFE) scoring.

**When to use:**

- Rank candidate theories based on their explanatory power and syntactic simplicity.
- Automate Ockham's Razor via the Cournot-Gaifman prior.

**Input:**

```json
{
  "observation": "O",
  "candidates": ["A & (A -> O)", "B & (B -> O)"]
}
```

**Returns:**

- `best_explanation`: The formula with the lowest VFE score.
- `vfe_score`: The calculated score combining complexity and surprisal.
- `ranking`: Ordered list of all candidates.

---

## Common Patterns

### Pattern 1: Prove → Counterexample → Explain

When a proof fails, find out why:

```
1. attempt: prove(premises, conclusion)
2. if fails: find_counterexample(premises, conclusion)
3. if counterexample found:
   - Explain the model to user
   - Show why conclusion doesn't follow
4. if no counterexample:
   - May need more premises
   - May need different formalization
```

### Pattern 2: Validate → Prove → Verify

For user-provided formulas:

```
1. check_well_formed(all_formulas)
2. if valid:
   - prove(premises, conclusion)
3. if proved:
   - Success!
4. else:
   - Try counterexample
```

### Pattern 3: Categorical Reasoning

Structured approach to category theory:

```
1. get_category_axioms("category")
2. Add specific morphisms/objects
3. verify_commutativity(paths...)
4. prove(premises, conclusion)
```

---

## Best Practices

### Logical Formulas

**Good:**

```
all x (man(x) -> mortal(x))
exists y (happy(y) & wise(y))
all x all y (knows(x,y) -> can_explain(x,y))
```

**Avoid:**

```
all x man(x) -> mortal(x)           # Missing parens around scope
ALL X (MAN(X) -> MORTAL(X))        # Use lowercase
all x (man(x)->mortal(x))          # Add spaces
```

### Quantifier Scopes

- **Always** use parentheses to delimit quantifier scope
- **Nested quantifiers:** `all x (all y (P(x,y) -> Q(x,y)))`
- **Multiple quantifiers:** `all x all y (P(x,y) -> Q(x,y))`

### Implication Chains

For `(A ∧ B) → C`:

```
all x ((premise1(x) & premise2(x)) -> conclusion(x))
```

Not:

```
all x (premise1(x) & premise2(x) -> conclusion(x))  # ambiguous precedence
```

---

## Response Strategies

### When Proof Succeeds

```
✓ The argument is **logically valid**.

Prover9 found a proof showing that [conclusion] necessarily follows from:
1. [premise 1]
2. [premise 2]
...

This means [plain English explanation of what was proven].
```

### When Proof Fails + Counterexample Found

```
✗ The argument is **invalid**.

I found a counterexample: [describe the model]

In this model:
- [premise 1] is satisfied ✓
- [premise 2] is satisfied ✓
- But [conclusion] is FALSE ✗

This shows that [conclusion] doesn't logically follow from the premises.
```

### When Syntax Errors Found

```
⚠️ Syntax issues detected:

[List specific errors with positions]

Corrected formulas:
- [show corrected versions]

[Explain what was wrong and why correction is needed]
```

---

## Advanced Techniques

### 1. Incremental Proof Building

For complex proofs, build up in steps:

```
1. Prove lemma 1
2. Prove lemma 2
3. Use lemmas as premises for main theorem
```

### 2. Proof by Contradiction

To prove P:

```
1. Assume -P (negation of P)
2. Try to prove(premises + [-P], conclusion=false)
3. If contradiction found, P must be true
```

### 3. Exploring Theory Space

```
1. Start with axioms
2. find_model to see what structures satisfy them
3. Try to prove interesting properties
4. If fail, find_counterexample to understand limitations
```

### 4. Categorical Functors

To verify functor F preserves composition:

```
1. get_category_axioms("category")
2. get_category_axioms("functor", "F")
3. Add: morphism(f), morphism(g), compose(g,f,gf)
4. Prove: compose(F(g), F(f), F(gf))
```

---

## Limitations

### Prover9 Limitations

- **First-order logic only** (no higher-order quantification)
- **Timeout:** Default 60 seconds (proof may exist but be too hard)
- **Search strategy:** May miss proofs; failure doesn't mean unprovable

### Mace4 Limitations

- **Finite models only** (can't find infinite counterexamples)
- **Domain size:** Searches up to size 10 by default (may miss larger counterexamples)
- **No model ≠ no counterexample** (could exist in larger domain)

### When to Combine Tools

- **Proof fails** → Try counterexample
- **No counterexample in small domains** → Try larger domain_size
- **Still no result** → Problem may be undecidable or need different formalization

---

## Error Recovery

### "Syntax error" from Prover9

→ Use `check_well_formed` to identify exact issue

### "Proof search failed"

→ Try `find_counterexample` to see if it's actually invalid

### "No model found within domain limits"

→ Try larger `domain_size` parameter (e.g., 15, 20)

### "Timeout"

→ Simplify premises or break into smaller lemmas

---

## Example Session

**User:** "Prove that if all birds fly and Tweety is a bird, then Tweety flies."

**Agent Response:**

```
I'll formalize this in first-order logic and verify it:

Premises:
1. all x (bird(x) -> flies(x))  [All birds fly]
2. bird(tweety)                  [Tweety is a bird]

Conclusion: flies(tweety)        [Tweety flies]

[Use prove tool]

✓ **Proof found!**

This is a valid instance of modus ponens:
- We know all birds fly (universal statement)
- Tweety is a bird (specific instance)
- Therefore Tweety flies (conclusion)

The proof is logically sound.
```

---

## Key Takeaway

**mcp-logic gives you formal verification** - use it to move beyond informal reasoning to rigorous proofs. When in doubt:

1. Formalize carefully in FOL
2. Validate syntax first
3. Try to prove
4. If fails, find counterexample to understand why
5. Explain results in plain language
