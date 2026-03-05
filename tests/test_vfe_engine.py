"""Tests for the VFE Engine abduction logic."""

import math

import pytest

from mcp_logic.vfe_engine import abductive_explain


class TestVFEEngine:
    """Tests for abductive reasoning optimization."""

    def test_basic_abduction(self) -> None:
        observation = "raining"
        # Simplest explanation should win
        candidates = ["raining", "raining & cloudy", "true | false"]
        # 'true | false' might be a tautology, let's see.
        # Our parser doesn't support 'true' keyword yet if I didn't add it to patterns.
        # Let's use real atoms.
        candidates = ["p", "p & q", "p | ~p"]

        res = abductive_explain(observation, candidates)

        # p | ~p is a tautology, filtered out.
        # p and p & q remain.
        # p has complexity 1, p & q has complexity 3.
        # p should definitely win.
        assert res.best_explanation is not None
        assert res.best_explanation.formula_str == "p"
        assert res.filtered_out_count == 1 # p | ~p filtered out

    def test_complexity_bias(self) -> None:
        # Multiple contingent explanations
        candidates = ["p & q", "p | q", "p"]
        # Complexities: 3, 3, 1
        res = abductive_explain("p", candidates)

        # p (complexity 1) should be first
        assert res.all_candidates[0].formula_str == "p"
        # Others follow
        assert len(res.all_candidates) == 3

    def test_hcc_filtering_contradiction(self) -> None:
        candidates = ["p & ~p", "q"]
        res = abductive_explain("r", candidates)

        assert res.best_explanation is not None
        assert res.best_explanation.formula_str == "q"
        assert res.filtered_out_count == 1

    def test_max_complexity_bound(self) -> None:
        # p & q & r & s & t -> many connectives.
        # Complexity: p(1) & q(1) = 3; & r(1) = 5; & s(1) = 7; & t(1) = 9.
        candidates = ["p & q & r & s & t"]
        res = abductive_explain("p", candidates, max_complexity=5)

        assert res.best_explanation is None
        assert res.filtered_out_count == 1

    def test_prior_probabilities(self) -> None:
        # 3 candidates. Rank 1, 2, 3.
        # mass: 1/2, 1/6, 1/12
        # total: 6/12 + 2/12 + 1/12 = 9/12 = 0.75
        # normalized: (1/2)/0.75 = 0.666, (1/6)/0.75 = 0.222, (1/12)/0.75 = 0.111
        candidates = ["p", "q", "r"]
        res = abductive_explain("s", candidates)

        # Sum of priors should be 1
        total_p = sum(c.prior for c in res.all_candidates)
        assert pytest.approx(total_p) == 1.0

        # Check ranks
        assert res.all_candidates[0].prior > res.all_candidates[1].prior
        assert res.all_candidates[1].prior > res.all_candidates[2].prior

    def test_vfe_score_calculation(self) -> None:
        candidates = ["p"]
        res = abductive_explain("p", candidates)

        # For 1 candidate, prior is 1.0. log(1.0) = 0.
        # Omega = complexity + 0 = 1.
        c = res.all_candidates[0]
        assert c.kl_divergence == 0
        assert c.vfe_score == 1.0

    def test_empty_candidates(self) -> None:
        res = abductive_explain("p", [])
        assert res.best_explanation is None
        assert "No valid contingent explanations" in res.message

    def test_invalid_candidate_syntax(self) -> None:
        candidates = ["p & @ & q", "r"]
        res = abductive_explain("s", candidates)

        assert res.best_explanation.formula_str == "r"
        assert res.filtered_out_count == 1
