import pytest

from mcp_logic.categorical_helpers import CategoricalHelpers
from mcp_logic.mace4_wrapper import Mace4Wrapper
from mcp_logic.syntax_validator import validate_formulas

from .conftest import has_mace4


@pytest.mark.skipif(not has_mace4(), reason="Mace4 binary not found")
@pytest.mark.asyncio
async def test_mace4_model_finding(prover_path):
    """Test Mace4 model finding"""
    mace4 = Mace4Wrapper(prover_path)

    # Test 1: Find a model for simple premises
    result = await mace4.find_model(["P(a)"], domain_size=2)
    assert result["result"] == "model_found"
    assert "model" in result
    assert result["model"]["domain_size"] == 2


@pytest.mark.skipif(not has_mace4(), reason="Mace4 binary not found")
@pytest.mark.asyncio
async def test_mace4_counterexample(prover_path):
    """Test Mace4 counterexample finding"""
    mace4 = Mace4Wrapper(prover_path)

    # Test 2: Find counterexample - P(a) doesn't imply P(b)
    result = await mace4.find_counterexample(["P(a)"], "P(b)", domain_size=2)
    assert result["result"] == "model_found"
    assert "interpretation" in result


def test_syntax_validator_valid():
    """Test syntax validation for valid formula"""
    result = validate_formulas(["all x (P(x) -> Q(x))"])
    assert result["valid"] is True
    assert not result["formula_results"][0]["errors"]


def test_syntax_validator_invalid():
    """Test syntax validation for invalid formula"""
    result = validate_formulas(["all x (P(x) -> Q(x)"])
    assert result["valid"] is False
    assert len(result["formula_results"][0]["errors"]) > 0


def test_categorical_helpers_category_axioms():
    """Test categorical reasoning helpers - category axioms"""
    helpers = CategoricalHelpers()
    axioms = helpers.category_axioms()
    assert len(axioms) > 0
    assert "formulas(assumptions)." in axioms[0] or "all " in axioms[0]


def test_categorical_helpers_functor_axioms():
    """Test categorical reasoning helpers - functor axioms"""
    helpers = CategoricalHelpers()
    axioms = helpers.functor_axioms("F")
    assert len(axioms) > 0
    assert any("f(" in a for a in axioms)


def test_categorical_helpers_commutativity():
    """Test categorical reasoning helpers - commutativity diagram"""
    helpers = CategoricalHelpers()
    premises, conclusion = helpers.verify_commutativity(
        path_a=["f", "g"], path_b=["h"], object_start="A", object_end="C"
    )
    assert len(premises) > 0
    assert "h" in conclusion
