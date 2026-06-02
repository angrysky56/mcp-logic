"""
Regression tests for two mcp-logic fixes (see AGEM docs §15):

1. Mace4 output parsing: a clean exhaustion ("exit (exhausted)") must be
   reported as 'no_model_found', NOT mislabeled 'timeout'. The old code matched
   the echoed 'max_seconds' assign() line and called every non-model result a
   timeout.
2. Negation normalization: callers may write '~' for negation; LADR only
   accepts '-'. normalize_formula() must translate so '~q(a)' does not raise a
   Mace4 'sread_term error'.
"""

import pytest
from pathlib import Path

from mcp_logic.syntax_validator import normalize_formula
from mcp_logic.mace4_wrapper import Mace4Wrapper

LADR_BIN = Path(__file__).resolve().parents[1] / "ladr" / "bin"


def test_normalize_tilde_to_dash():
    assert normalize_formula("~q(a)") == "-q(a)"
    assert normalize_formula("p(a) -> ~q(a)") == "p(a) -> -q(a)"
    assert normalize_formula("-q(a)") == "-q(a)"  # idempotent
    assert normalize_formula("p(a)") == "p(a)"  # no-op when no negation


@pytest.fixture
def mace4():
    if not (LADR_BIN / "mace4").exists():
        pytest.skip("Mace4 binary not present")
    return Mace4Wrapper(LADR_BIN)


@pytest.mark.asyncio
async def test_tilde_negation_does_not_crash(mace4):
    """'~q(a)' must be accepted (normalized to '-q(a)') and be consistent."""
    r = await mace4.find_counterexample(premises=["~q(a)"], conclusion="$F")
    assert r["result"] == "model_found"  # consistent


@pytest.mark.asyncio
async def test_unsat_triple_is_no_model_not_timeout(mace4):
    """Pairwise-consistent, jointly-inconsistent triple must report
    'no_model_found' (the set is contradictory), NOT 'timeout'."""
    r = await mace4.find_counterexample(
        premises=["p(a)", "p(a) -> q(a)", "~q(a)"], conclusion="$F"
    )
    assert r["result"] == "no_model_found"


@pytest.mark.asyncio
async def test_consistent_pair_is_model_found(mace4):
    """A satisfiable set must report 'model_found'."""
    r = await mace4.find_counterexample(
        premises=["p(a)", "p(a) -> q(a)"], conclusion="$F"
    )
    assert r["result"] == "model_found"
