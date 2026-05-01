import os
import tempfile
from pathlib import Path

import pytest

from mcp_logic.server import LogicEngine


@pytest.mark.skipif(
    not os.path.exists("/home/ty/Repositories/ai_workspace/mcp-logic/ladr/bin"),
    reason="LADR bin not found",
)
@pytest.mark.asyncio
async def test_direct_prover9():
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

    fd, path = tempfile.mkstemp(suffix=".in", text=True)
    with os.fdopen(fd, "w") as f:
        f.write(content)

    engine = LogicEngine("/home/ty/Repositories/ai_workspace/mcp-logic/ladr/bin")
    result = await engine.run_prover(Path(path))
    print("\nProver Result:", result)

    assert result["result"] == "proved"
