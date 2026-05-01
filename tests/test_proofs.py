import pytest

from mcp_logic.server import LogicEngine

from .conftest import has_prover9


@pytest.mark.skipif(not has_prover9(), reason="Prover9 binary not found")
@pytest.mark.asyncio
async def test_socrates_mortality(prover_path):
    """Test basic syllogistic reasoning"""
    engine = LogicEngine(str(prover_path))

    input_file = engine.create_input_file(
        premises=["all x (man(x) -> mortal(x))", "man(socrates)"],
        goal="mortal(socrates)",
    )

    result = await engine.run_prover(input_file)
    assert result["result"] == "proved"


@pytest.mark.skipif(not has_prover9(), reason="Prover9 binary not found")
@pytest.mark.asyncio
async def test_complex_proof(prover_path):
    """Test more complex logical reasoning with multiple premises"""
    engine = LogicEngine(str(prover_path))

    premises = [
        "all x all y (teaches(x,y) -> knows(x,y))",
        "all x all y (admires(x,y) -> wants_to_learn_from(x,y))",
        "all x all y (wants_to_learn_from(x,y) & knows(y,logic) -> seeks_wisdom(x,y))",
        "teaches(aristotle,logic)",
        "admires(plato,aristotle)",
    ]

    input_file = engine.create_input_file(
        premises=premises, goal="seeks_wisdom(plato,aristotle)"
    )

    result = await engine.run_prover(input_file)
    assert result["result"] == "proved"


@pytest.mark.skipif(not has_prover9(), reason="Prover9 binary not found")
@pytest.mark.asyncio
async def test_syntax_validation(prover_path):
    """Test syntax validation on invalid input"""
    engine = LogicEngine(str(prover_path))

    input_file = engine.create_input_file(
        premises=["invalid syntax here"], goal="this_is_not_valid"
    )

    result = await engine.run_prover(input_file)
    assert result["result"] == "error"
    assert "error" in result
