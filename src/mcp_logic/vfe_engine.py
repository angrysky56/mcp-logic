"""
Variational Free Energy (VFE) engine for abductive reasoning.

Implements the inductive optimizer that ranks candidate explanations
based on syntactic complexity and semantic surprisal (KL-divergence).
Uses a Cournot-Gaifman non-dogmatic prior.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

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


@dataclass(frozen=True)
class AbductionResult:
    """The result of an abductive explanation process."""

    best_explanation: Optional[CandidateScore]
    all_candidates: List[CandidateScore]
    filtered_out_count: int
    message: str


def abductive_explain(
    observation_str: str, candidates: List[str], max_complexity: int = 20
) -> AbductionResult:
    """
    Find the VFE-minimizing abductive explanation for an observation.

    Args:
        observation_str: The formula string representing the observation.
        candidates: A list of candidate formula strings to evaluate.
        max_complexity: Maximum complexity bound for explanations.

    Returns:
        An AbductionResult containing the best explanation and ranking.
    """
    # 1. Parse observation (for validation, though not strictly needed for scoring here)
    try:
        parse(observation_str)
    except ParseError as e:
        return AbductionResult(None, [], 0, f"Invalid observation: {e}")

    scored_candidates: List[CandidateScore] = []
    filtered_out = 0

    # 2. HCC Filtering and Complexity Bound
    valid_candidates: List[Tuple[str, int]] = []
    for c_str in candidates:
        try:
            ast = parse(c_str)
            c_comp = complexity(ast)

            # Bound check
            if c_comp > max_complexity:
                filtered_out += 1
                continue

            # HCC filtering: explanation must be contingent
            # (Contradictions are impossible, tautologies are empty)
            hcc_res = check_contingency(c_str)
            if not hcc_res.is_contingent:
                filtered_out += 1
                continue

            valid_candidates.append((c_str, c_comp))

        except ParseError:
            filtered_out += 1
            continue

    if not valid_candidates:
        return AbductionResult(
            None,
            [],
            filtered_out,
            "No valid contingent explanations found within complexity bound.",
        )

    # 3. Sort by Syntactic Complexity (Solomonoff Case)
    # This prepares for Cournot-Gaifman prior assignment
    valid_candidates.sort(key=lambda x: x[1])

    # 4. Cournot-Gaifman Prior Initialization
    # m_i = 1 / (i * (i + 1))
    priors = []
    total_mass = 0.0
    for i in range(1, len(valid_candidates) + 1):
        mass = 1.0 / (i * (i + 1))
        priors.append(mass)
        total_mass += mass

    # Normalize priors to sum to 1 over the finite working set
    normalized_priors = [m / total_mass for m in priors]

    # 5. Calculate VFE Weight (Omega)
    # Omega = Complexity + KL-Divergence
    # KL-Divergence = -log(prior) [Point mass simplification]
    for idx, (c_str, c_comp) in enumerate(valid_candidates):
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
            )
        )

    # 6. Sorting and Selection (VFE-Contraction)
    scored_candidates.sort(key=lambda x: x.vfe_score)

    best = scored_candidates[0]

    return AbductionResult(
        best_explanation=best,
        all_candidates=scored_candidates,
        filtered_out_count=filtered_out,
        message=f"Success. Ranked {len(scored_candidates)} candidates.",
    )
