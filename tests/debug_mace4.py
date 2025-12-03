"""
Quick debug test for Mace4
"""

import subprocess
import tempfile
import os
from pathlib import Path

ladr_path = Path("/home/ty/Repositories/mcp-logic/ladr/bin")
mace4_exe = ladr_path / "mace4"

# Create simple test input
content = """
assign(domain_size, 2).
assign(iterate_up_to, 0).
assign(max_seconds, 10).

formulas(assumptions).
P(a).
end_of_list.
"""

fd, path = tempfile.mkstemp(suffix=".in", text=True)
with os.fdopen(fd, "w") as f:
    f.write(content)

print(f"Running: {mace4_exe} -f {path}")
result = subprocess.run([str(mace4_exe), "-f", str(path)], capture_output=True, text=True, timeout=10, cwd=str(mace4_exe.parent))

print("STDOUT:")
print(result.stdout)
print("\nSTDERR:")
print(result.stderr)
print(f"\nReturn code: {result.returncode}")

# Cleanup
Path(path).unlink()
