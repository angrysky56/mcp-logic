"""
Variational Free Energy (VFE) engine for abductive reasoning.

Abduction is inference to the best explanation: given an observation ``O`` and
a background theory ``T``, find the explanation ``E`` (from a candidate set)
such that ``T ∪ {E} ⊨ O`` while ``T ∪ {E}`` stays consistent, preferring the
simplest such ``E`` (Occam's razor).

This module combines a *logical* filter (does the candidate, together with the
background theory, actually entail the observation and remain consistent?) with
an *inductive* preference ordering (syntactic complexity + a Cournot–Gaifman
non-dogmatic prior, expressed as a Variational Free Energy weight).

Two scopes are supported:

* **Propositional** (``abductive_explain``) — candidates / observation /
  background are parsed by :mod:`mcp_logic.formula_ast`; entailment and
  consistency are decided with the HCC contingency checker.
* **First-order** (``abductive_explain_fol``) — entailment is delegated to
  Prover9 (``T ∪ {E} ⊢ O``) and consistency to Mace4 (a finite model of
  ``T ∪ {E}`` exists), via injected async callables so this module stays
  decoupled from the server's engine.

Both paths share the same VFE ranking (``_rank``): tiered by logical adequacy
first, then ordered by Variational Free Energy (syntactic complexity + a
Cournot–Gaifman non-dogmatic prior) within each tier.
"""

from __future__ import annotations

import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from mcp_logic.formula_ast import ParseError, complexity, parse
from mcp_logic.hcc_prover import check_contingency


@dataclass(frozen=True)
class CandidateScore:
    """A scored candidate explanation."""

    formula_str: str
    complexity: int
    prior: float
    kl_divergence: float
    vfe_score: float  # Omega value
    is_contingent: bool
    explains: bool  # background ∪ {candidate} ⊨ observation
    consistent: bool  # background ∪ {candidate} is satisfiable


@dataclass(frozen=True)
class AbductionResult:
    """The result of an abductive explanation process."""

    best_explanation: CandidateScore | None
    all_candidates: list[CandidateScore]
    filtered_out_count: int
    message: str


def _conjoin(formulas: list[str]) -> str:
    """Join formula strings into a single parenthesised conjunction."""
    return " & ".join(f"({f})" for f in formulas)


def _entails(background: list[str], explanation: str, observation: str) -> bool:
    """Return True if ``background ∪ {explanation} ⊨ observation``.

    Implemented by checking whether the material implication
    ``(b1 & ... & explanation) -> observation`` is a tautology.

    Args:
        background: Background theory formula strings (may be empty).
        explanation: The candidate explanation formula string.
        observation: The observation formula string.

    Returns:
        True if the antecedent logically forces the observation.
    """
    antecedent = _conjoin([*background, explanation])
    implication = f"({antecedent}) -> ({observation})"
    try:
        return check_contingency(implication).is_tautology
    except (ValueError, ParseError):
        return False


def _consistent(background: list[str], explanation: str) -> bool:
    """Return True if ``background ∪ {explanation}`` is satisfiable.

    Args:
        background: Background theory formula strings (may be empty).
        explanation: The candidate explanation formula string.

    Returns:
        True unless the conjunction is a contradiction.
    """
    conj = _conjoin([*background, explanation])
    try:
        return not check_contingency(conj).is_contradiction
    except (ValueError, ParseError):
        return False


def abductive_explain(
    observation_str: str,
    candidates: list[str],
    max_complexity: int = 20,
    background: list[str] | None = None,
) -> AbductionResult:
    """
    Find the best abductive explanation for an observation.

    Ranking is tiered, then ordered by Variational Free Energy within each tier:

    1. **Explanations** — candidates that, together with the background theory,
       entail the observation and remain consistent. These are true
       explanations and are always preferred.
    2. **Consistent-but-insufficient** — candidates consistent with the theory
       that do not (by themselves) entail the observation. Returned as
       fallbacks when no candidate fully explains the observation.

    Within each tier the simplest candidate (lowest VFE = complexity + KL term)
    wins. Candidates that are contradictions, tautologies, inconsistent with
    the background theory, unparseable, or over the complexity bound are
    filtered out.

    Args:
        observation_str: The formula string representing the observation.
        candidates: Candidate explanation formula strings to evaluate.
        max_complexity: Maximum syntactic complexity allowed for a candidate.
        background: Optional background theory. Without it, "explains" reduces
            to the candidate directly entailing the observation.

    Returns:
        An AbductionResult with the best explanation and the full ranking.
    """
    background = background or []

    # 1. Parse observation (and validate the background theory).
    try:
        parse(observation_str)
        for b in background:
            parse(b)
    except ParseError as e:
        return AbductionResult(None, [], 0, f"Invalid observation/background: {e}")

    filtered_out = 0

    # 2. Logical + complexity filtering.
    #    Keep only parseable, contingent, in-bound candidates that stay
    #    consistent with the background theory.
    valid_candidates: list[tuple[str, int, bool]] = []  # (str, complexity, explains)
    for c_str in candidates:
        try:
            ast = parse(c_str)
        except ParseError:
            filtered_out += 1
            continue

        c_comp = complexity(ast)
        if c_comp > max_complexity:
            filtered_out += 1
            continue

        # A useful explanation is itself contingent (not a tautology — which
        # explains nothing — nor a contradiction — which is impossible).
        if not check_contingency(c_str).is_contingent:
            filtered_out += 1
            continue

        # Must be jointly consistent with the background theory.
        if not _consistent(background, c_str):
            filtered_out += 1
            continue

        explains = _entails(background, c_str, observation_str)
        valid_candidates.append((c_str, c_comp, explains))

    # 3. Rank the survivors with the shared VFE ranker.
    return _rank(valid_candidates, filtered_out, bool(background))


def _rank(
    valid_candidates: list[tuple[str, int, bool]],
    filtered_out: int,
    background_present: bool,
) -> AbductionResult:
    """Rank pre-filtered candidates by Variational Free Energy.

    Shared by the propositional (:func:`abductive_explain`) and first-order
    (:func:`abductive_explain_fol`) paths so both order candidates identically.

    Ranking is tiered: candidates that entail the observation (``explains``)
    come first, then by VFE (lower wins). VFE = syntactic complexity + KL term,
    where KL = ``-log(prior)`` and the prior is the Cournot–Gaifman
    non-dogmatic mass ``1 / (i * (i + 1))`` over the complexity-sorted list.

    Args:
        valid_candidates: ``(formula_str, complexity, explains)`` triples that
            already passed each path's logical/complexity filters.
        filtered_out: Count of candidates rejected during filtering (for the
            returned :class:`AbductionResult`).
        background_present: Whether a background theory was supplied — only
            affects the human-readable message wording.

    Returns:
        An :class:`AbductionResult` with the best explanation and full ranking.
    """
    if not valid_candidates:
        return AbductionResult(
            None,
            [],
            filtered_out,
            "No valid contingent explanations found within complexity bound.",
        )

    # Inductive ordering by syntactic complexity (Solomonoff/Occam) to assign
    # the Cournot–Gaifman prior.
    valid_candidates.sort(key=lambda x: x[1])

    priors: list[float] = []
    total_mass = 0.0
    for i in range(1, len(valid_candidates) + 1):
        mass = 1.0 / (i * (i + 1))  # Cournot–Gaifman non-dogmatic prior
        priors.append(mass)
        total_mass += mass
    normalized_priors = [m / total_mass for m in priors]

    # VFE weight: Omega = complexity + KL, with KL = -log(prior).
    scored_candidates: list[CandidateScore] = []
    for idx, (c_str, c_comp, explains) in enumerate(valid_candidates):
        prior = normalized_priors[idx]
        kl = -math.log(prior)
        omega = c_comp + kl
        scored_candidates.append(
            CandidateScore(
                formula_str=c_str,
                complexity=c_comp,
                prior=prior,
                kl_divergence=kl,
                vfe_score=omega,
                is_contingent=True,
                explains=explains,
                consistent=True,
            )
        )

    # Tiered selection: explanations first (explains=True), then by VFE.
    scored_candidates.sort(key=lambda c: (not c.explains, c.vfe_score))
    best = scored_candidates[0]

    explainers = [c for c in scored_candidates if c.explains]
    if explainers:
        message = (
            "Best explanation entails the observation"
            + (" under the background theory" if background_present else "")
            + f". Ranked {len(scored_candidates)} candidate(s); "
            f"{len(explainers)} logically explain the observation."
        )
    else:
        message = (
            "No candidate logically entails the observation"
            + (" under the given background theory" if background_present else "")
            + ". Returning the simplest consistent candidate as a weak "
            f"hypothesis. Ranked {len(scored_candidates)} candidate(s). "
            "Supplying a 'background' theory linking the candidates to the "
            "observation usually yields a genuine explanation."
        )

    return AbductionResult(
        best_explanation=best,
        all_candidates=scored_candidates,
        filtered_out_count=filtered_out,
        message=message,
    )


# Token pattern for approximating first-order formula complexity: identifiers
# (predicates, functions, variables, quantifier keywords) plus the logical
# connectives and equality.
_FOL_TOKEN_RE = re.compile(r"[A-Za-z_]\w*|<->|->|&|\||~|=")


def fol_complexity(formula_str: str) -> int:
    """Approximate the syntactic complexity of a first-order formula.

    The propositional path uses an AST node count, but FOL formulas are not
    parsed by :mod:`mcp_logic.formula_ast`. Instead we count syntactic tokens
    — identifiers (predicates, functions, variables, ``all``/``exists``) and
    connectives (``->``, ``<->``, ``&``, ``|``, ``~``, ``=``). This preserves
    the Occam ordering (simpler formulas score lower) without a full parser.

    Args:
        formula_str: A first-order formula string.

    Returns:
        Token count used as the complexity measure.
    """
    return len(_FOL_TOKEN_RE.findall(formula_str))


async def abductive_explain_fol(
    observation_str: str,
    candidates: list[str],
    prove_fn: Callable[[list[str], str], Awaitable[bool]],
    model_fn: Callable[[list[str]], Awaitable[bool]] | None = None,
    max_complexity: int = 20,
    background: list[str] | None = None,
) -> AbductionResult:
    """First-order inference to the best explanation, via Prover9 + Mace4.

    Mirrors :func:`abductive_explain` but defers the two logical checks to
    injected async callables so this module never imports the server engine:

    * **Entailment** — ``prove_fn(background + [candidate], observation)`` must
      return True (Prover9 proves the observation).
    * **Consistency** — ``model_fn(background + [candidate])`` must return True
      (Mace4 finds a finite model). When ``model_fn`` is None (no model finder
      available) the consistency filter is skipped and every candidate is
      treated as consistent.

    Candidates over ``max_complexity`` (token count) or inconsistent with the
    background theory are filtered out; the rest are ranked by the shared
    :func:`_rank` VFE ranker.

    Args:
        observation_str: The first-order formula that was observed.
        candidates: Candidate explanation formulas to evaluate.
        prove_fn: Async ``(premises, conclusion) -> bool`` entailment oracle.
        model_fn: Optional async ``(premises) -> bool`` satisfiability oracle.
        max_complexity: Maximum candidate token count allowed.
        background: Optional background theory (domain rules).

    Returns:
        An :class:`AbductionResult` with the best explanation and full ranking.
    """
    background = background or []

    filtered_out = 0
    valid_candidates: list[tuple[str, int, bool]] = []

    for c_str in candidates:
        comp = fol_complexity(c_str)
        if comp > max_complexity:
            filtered_out += 1
            continue

        # Consistency: background ∪ {candidate} must have a model. A candidate
        # that contradicts the theory explains nothing and is discarded.
        if model_fn is not None:
            consistent = await model_fn([*background, c_str])
            if not consistent:
                filtered_out += 1
                continue

        # Entailment: does Prover9 derive the observation from background +
        # candidate?
        explains = await prove_fn([*background, c_str], observation_str)
        valid_candidates.append((c_str, comp, explains))

    return _rank(valid_candidates, filtered_out, bool(background))
