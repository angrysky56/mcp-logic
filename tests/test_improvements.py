"""Regression tests for the logical-operation and agent-UX improvements.

Covers:
- Proof block extraction (previously always empty).
- Output slimming: raw dumps suppressed unless verbose=True.
- Counterexample structured model population.
- Abduction that actually uses the observation + background theory.
"""

import pytest

from mcp_logic.server import LogicEngine, _extract_proof, _extract_proof_stats
from mcp_logic.vfe_engine import (
    abductive_explain,
    abductive_explain_fol,
    fol_complexity,
)

from .conftest import has_mace4, has_prover9

# A trimmed but representative Prover9 success output.
_PROVER9_OUTPUT = """\
============================== PROOF =================================

% Proof 1 at 0.00 (+ 0.00) seconds.
% Length of proof is 7.
% Level of proof is 3.

1 (all x (man(x) -> mortal(x))).  [assumption].
5 mortal(socrates).  [resolve(3,a,4,a)].
7 $F.  [resolve(5,a,6,a)].

============================== end of proof ==========================
"""


class TestProofExtraction:
    """The old split('PROOF =') logic always returned ''."""

    def test_proof_block_is_extracted(self):
        proof = _extract_proof(_PROVER9_OUTPUT)
        assert proof, "Proof block should not be empty"
        assert "$F." in proof
        assert "mortal(socrates)" in proof

    def test_proof_excludes_banner_lines(self):
        proof = _extract_proof(_PROVER9_OUTPUT)
        assert "====" not in proof
        assert "end of proof" not in proof

    def test_no_proof_returns_empty(self):
        assert _extract_proof("SEARCH FAILED\n") == ""

    def test_stats_extracted(self):
        stats = _extract_proof_stats(_PROVER9_OUTPUT)
        assert stats["length"] == 7
        assert stats["level"] == 3
        assert stats["seconds"] == 0.0


@pytest.mark.skipif(not has_prover9(), reason="Prover9 binary not found")
@pytest.mark.asyncio
class TestProveOutputShape:
    async def test_proved_has_clean_proof_no_raw_by_default(self, prover_path):
        engine = LogicEngine(str(prover_path))
        f = engine.create_input_file(
            ["all x (man(x) -> mortal(x))", "man(socrates)"], "mortal(socrates)"
        )
        result = await engine.run_prover(f)
        assert result["result"] == "proved"
        assert result["proof"], "proof should be populated"
        assert "complete_output" not in result, "raw output must be opt-in"
        assert "stats" in result

    async def test_verbose_includes_raw(self, prover_path):
        engine = LogicEngine(str(prover_path))
        f = engine.create_input_file(
            ["all x (man(x) -> mortal(x))", "man(socrates)"], "mortal(socrates)"
        )
        result = await engine.run_prover(f, verbose=True)
        assert "complete_output" in result

    async def test_unprovable_offers_hint(self, prover_path):
        engine = LogicEngine(str(prover_path))
        f = engine.create_input_file(["all x (man(x) -> mortal(x))"], "mortal(socrates)")
        result = await engine.run_prover(f)
        assert result["result"] == "unprovable"
        assert "find_counterexample" in result.get("hint", "")


@pytest.mark.skipif(not has_mace4(), reason="Mace4 binary not found")
@pytest.mark.asyncio
class TestCounterexampleShape:
    async def test_structured_model_populated_no_raw(self, prover_path):
        from mcp_logic.mace4_wrapper import Mace4Wrapper

        mace4 = Mace4Wrapper(prover_path)
        result = await mace4.find_counterexample(["P(a)"], "P(b)", domain_size=2)
        assert result["result"] == "model_found"
        assert "complete_output" not in result
        assert result["model"]["predicates"], "predicates should be parsed"
        assert result["model"]["raw_interpretation"]


class TestAbductionUsesObservation:
    def test_background_enables_real_explanation(self):
        res = abductive_explain(
            "wet_grass",
            ["rained", "sprinkler"],
            background=["rained -> wet_grass"],
        )
        assert res.best_explanation.formula_str == "rained"
        assert res.best_explanation.explains is True

    def test_without_link_no_candidate_explains(self):
        res = abductive_explain("wet_grass", ["rained", "sprinkler"])
        assert all(not c.explains for c in res.all_candidates)
        assert res.best_explanation is not None  # still returns weak hypothesis

    def test_candidate_directly_entailing_is_flagged(self):
        # 'p & q' entails 'p' with no background needed.
        res = abductive_explain("p", ["p & q", "r"])
        by_name = {c.formula_str: c for c in res.all_candidates}
        assert by_name["p & q"].explains is True
        assert by_name["r"].explains is False
        assert res.best_explanation.explains is True

    def test_inconsistent_with_background_filtered(self):
        # 'sun' is inconsistent with background '~sun', so it's filtered out.
        res = abductive_explain(
            "wet_grass",
            ["sun", "rained"],
            background=["~sun", "rained -> wet_grass"],
        )
        names = [c.formula_str for c in res.all_candidates]
        assert "sun" not in names
        assert res.filtered_out_count >= 1


class TestFolComplexity:
    """Token-count complexity used by the first-order abduction path."""

    def test_counts_predicate_and_argument(self):
        # 'man(socrates)' -> tokens: man, socrates
        assert fol_complexity("man(socrates)") == 2

    def test_quantified_formula_is_more_complex(self):
        assert fol_complexity("all x (man(x) -> mortal(x))") > fol_complexity(
            "man(socrates)"
        )

    def test_connectives_counted(self):
        # p(a) & q(a): p, a, &, q, a -> 5 tokens
        assert fol_complexity("p(a) & q(a)") == 5


class TestAbductionFolRouting:
    """abductive_explain_fol with injected oracles (no binary required)."""

    @pytest.mark.asyncio
    async def test_entailing_candidate_is_best(self):
        async def prove_fn(premises, conclusion):
            # Observation follows only when 'man(socrates)' is assumed.
            return any("man(socrates)" in p for p in premises)

        async def model_fn(premises):
            return True

        res = await abductive_explain_fol(
            "mortal(socrates)",
            ["man(socrates)", "rich(socrates)"],
            prove_fn,
            model_fn,
            background=["all x (man(x) -> mortal(x))"],
        )
        assert res.best_explanation.formula_str == "man(socrates)"
        assert res.best_explanation.explains is True

    @pytest.mark.asyncio
    async def test_inconsistent_candidate_filtered(self):
        async def prove_fn(premises, conclusion):
            return True

        async def model_fn(premises):
            # A candidate containing 'bad' has no model (inconsistent).
            return not any("bad" in p for p in premises)

        res = await abductive_explain_fol(
            "mortal(socrates)",
            ["bad(socrates)", "man(socrates)"],
            prove_fn,
            model_fn,
        )
        names = [c.formula_str for c in res.all_candidates]
        assert "bad(socrates)" not in names
        assert res.filtered_out_count >= 1

    @pytest.mark.asyncio
    async def test_no_model_fn_skips_consistency(self):
        async def prove_fn(premises, conclusion):
            return False

        res = await abductive_explain_fol(
            "p(a)",
            ["q(a)", "r(a)"],
            prove_fn,
            None,  # no model finder -> consistency filter skipped
        )
        assert len(res.all_candidates) == 2
        assert res.best_explanation is not None
        assert all(not c.explains for c in res.all_candidates)


@pytest.mark.skipif(not has_prover9(), reason="Prover9 binary not found")
@pytest.mark.asyncio
class TestAbductionFolIntegration:
    """End-to-end FOL abduction against the real Prover9/Mace4 binaries."""

    async def test_real_prover_entailment(self, prover_path):
        engine = LogicEngine(str(prover_path))

        async def prove_fn(premises, conclusion):
            f = engine.create_input_file(premises, conclusion)
            r = await engine.run_prover(f, timeout=10)
            return r.get("result") == "proved"

        async def model_fn(premises):
            if engine.mace4 is None:
                return True
            r = await engine.mace4.find_model(premises, timeout=10)
            return r.get("result") == "model_found"

        res = await abductive_explain_fol(
            "mortal(socrates)",
            ["man(socrates)", "rich(socrates)"],
            prove_fn,
            model_fn,
            background=["all x (man(x) -> mortal(x))"],
        )
        assert res.best_explanation.formula_str == "man(socrates)"
        assert res.best_explanation.explains is True
