from mcp_logic.server import LogicEngine
import tempfile
import os

def test_direct_prover9():
    """Test direct Prover9 execution with exact file contents"""
    # Create test file
    content = """formulas(assumptions).
all x (man(x) -> mortal(x)).
man(socrates).
end_of_list.

formulas(goals).
mortal(socrates).
end_of_list.
"""
    
    fd, path = tempfile.mkstemp(suffix='.in', text=True)
    with os.fdopen(fd, 'w') as f:
        f.write(content)
        
    engine = LogicEngine("F:/Prover9-Mace4/bin-win32")
    result = engine._run_prover(path)
    print("\nProver Result:", result)
    
    assert result["result"] == "proved"