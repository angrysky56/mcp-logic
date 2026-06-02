"""
Hypersequent Contingency Calculus (HCC) prover.

Implements the deductive contingency checker from Pulcini & Varzi's paper:
"A Hypersequent Calculus for Classical Contingencies".

This module handles the bottom-up decomposition of propositional formulas
into hyperclauses and evaluates them against the axiomatic side-conditions.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from mcp_logic.formula_ast import (
    And,
    Formula,
    Not,
    Or,
    Var,
    parse,
    to_nnf,
)

# A Component is a frozenset of formulas (representing a disjunction)
Component = frozenset[Formula]

# A Hypersequent is a tuple of Components (representing a conjunction)
Hypersequent = tuple[Component, ...]


@dataclass(frozen=True)
class ProofStep:
    """A single step in the HCC decomposition process."""

    rule: str
    before: Hypersequent
    after: Hypersequent
    formula: Formula | None = None


@dataclass(frozen=True)
class ContingencyResult:
    """The result of a contingency check."""

    is_contingent: bool
    is_tautology: bool
    is_contradiction: bool
    proof_trace: list[ProofStep]
    final_hyperclause: Hypersequent
    message: str


def check_contingency(formula_str: str) -> ContingencyResult:
    """
    Check if a propositional formula is truth-functionally contingent using HCC.

    Args:
        formula_str: The formula string to check.

    Returns:
        A ContingencyResult containing the truth status and proof trace.
    """
    # 1. Parse and convert to NNF
    try:
        raw_formula = parse(formula_str)
        formula = to_nnf(raw_formula)
    except Exception as e:
        # Re-wrap or broaden if needed, but basic validation is done in validator.py
        raise ValueError(f"Invalid formula: {e}") from e

    # 2. Initialize hypersequent: One component containing the single formula
    initial_component: Component = frozenset({formula})
    current_hs: Hypersequent = (initial_component,)
    trace: list[ProofStep] = []

    # 3. Bottom-up decomposition
    while True:
        next_hs, rule, target_f = _apply_next_decomposition(current_hs)
        if next_hs is None:
            break
        trace.append(ProofStep(rule, current_hs, next_hs, target_f))
        current_hs = next_hs

    # 4. Axiomatic check (Condition A and B)
    # At this point current_hs is a hyperclause (all formulas are literals)
    non_tautological, _ = _check_condition_a(current_hs)
    non_contradictory, _ = _check_condition_b(current_hs)

    is_contingent = non_tautological and non_contradictory

    # Determine status message
    if is_contingent:
        msg = "Formula is contingent."
    elif not non_tautological:
        msg = "Formula is a tautology (failed Condition A: all components contain complementary literals)."
    elif not non_contradictory:
        msg = "Formula is a contradiction (failed Condition B: no consistent cross-clause exists)."
    else:
        msg = "Formula is not contingent."

    return ContingencyResult(
        is_contingent=is_contingent,
        is_tautology=not non_tautological,
        is_contradiction=not non_contradictory,
        proof_trace=trace,
        final_hyperclause=current_hs,
        message=msg,
    )


def _apply_next_decomposition(
    hs: Hypersequent,
) -> tuple[Hypersequent | None, str, Formula | None]:
    """Find the first non-literal and apply its rule. OR before AND for efficiency."""

    # Try OR rule first (non-branching in terms of components)
    for i, component in enumerate(hs):
        for f in component:
            if isinstance(f, Or):
                new_component = set(component)
                new_component.remove(f)
                new_component.add(f.left)
                new_component.add(f.right)

                new_hs_list = list(hs)
                new_hs_list[i] = frozenset(new_component)
                return tuple(new_hs_list), "OR", f

    # Try AND rule (branching: one component becomes two)
    for i, component in enumerate(hs):
        for f in component:
            if isinstance(f, And):
                # G | Γ, A & B  ->  G | Γ, A | Γ, B
                # i.e., replace component i with two components
                prefix = hs[:i]
                suffix = hs[i + 1 :]

                gamma = set(component)
                gamma.remove(f)

                c_left = frozenset(gamma | {f.left})
                c_right = frozenset(gamma | {f.right})

                return prefix + (c_left, c_right) + suffix, "AND", f

    return None, "", None


def _check_condition_a(hyperclause: Hypersequent) -> tuple[bool, list[int]]:
    """Condition A: Hypersequent is non-tautological if it has at least one consistent component."""
    inconsistent_indices = []
    has_consistent = False

    for i, component in enumerate(hyperclause):
        if _is_consistent(component):
            has_consistent = True
        else:
            inconsistent_indices.append(i)

    return has_consistent, inconsistent_indices


def _check_condition_b(
    hyperclause: Hypersequent,
) -> tuple[bool, set[Formula] | None]:
    """Condition B: Hypersequent is non-contradictory if some cross-clause is consistent."""

    # We need to select 1 literal from component 0, 1 from component 1, etc.
    # and see if the resulting set is consistent.

    # Convert components to lists for itertools
    comp_lists = [list(c) for c in hyperclause]

    for selection in itertools.product(*comp_lists):
        if _is_consistent(frozenset(selection)):
            return True, set(selection)

    return False, None


def _is_consistent(clause: frozenset[Formula]) -> bool:
    """A set of literals is consistent if it contains no pair p, ~p."""
    atoms = set()
    negated_atoms = set()

    for f in clause:
        if isinstance(f, Var):
            atoms.add(f.name)
        elif isinstance(f, Not) and isinstance(f.inner, Var):
            negated_atoms.add(f.inner.name)
        else:
            # Should not happen in a hyperclause
            continue

    return atoms.isdisjoint(negated_atoms)


def format_hypersequent(hs: Hypersequent) -> str:
    """Pretty print a hypersequent."""
    components = []
    for c in hs:
        # Join with comma, wrap in brackets
        formulas = sorted([str(f) for f in c])
        components.append(f"[{', '.join(formulas)}]")

    return " | ".join(components)
