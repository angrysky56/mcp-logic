import pytest
from pathlib import Path
from mcp_logic.server import LogicEngine

def test_socrates_mortality():
    """Test basic syllogistic reasoning"""
    engine = LogicEngine("F:/Prover9-Mace4/bin-win32")
    
    input_file = engine._create_input_file(
        premises=["all x (man(x) -> mortal(x))", "man(socrates)"],
        goal="mortal(socrates)"
    )
    
    result = engine._run_prover(input_file)
    assert result["result"] == "proved"

def test_complex_proof():
    """Test more complex logical reasoning with multiple premises"""
    engine = LogicEngine("F:/Prover9-Mace4/bin-win32")
    
    premises = [
        "all x all y (teaches(x,y) -> knows(x,y))",
        "all x all y (admires(x,y) -> wants_to_learn_from(x,y))",
        "all x all y (wants_to_learn_from(x,y) & knows(y,logic) -> seeks_wisdom(x,y))",
        "teaches(aristotle,logic)",
        "admires(plato,aristotle)"
    ]
    
    input_file = engine._create_input_file(
        premises=premises,
        goal="seeks_wisdom(plato,aristotle)"
    )
    
    result = engine._run_prover(input_file)
    assert result["result"] == "proved"

def test_syntax_validation():
    """Test syntax validation on invalid input"""
    engine = LogicEngine("F:/Prover9-Mace4/bin-win32")
    
    input_file = engine._create_input_file(
        premises=["invalid syntax here"],
        goal="this_is_not_valid"
    )
    
    result = engine._run_prover(input_file)
    assert result["result"] == "error"
    assert "error" in result