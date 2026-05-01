from pathlib import Path

from mcp_logic.mace4_wrapper import Mace4Wrapper

ladr_path = Path("/home/ty/Repositories/ai_workspace/mcp-logic/ladr/bin")
mace4 = Mace4Wrapper(ladr_path)
result = mace4.find_model(["P(a)"], domain_size=2)
print("RESULT:", result["result"])
if "model" in result:
    print("DOMAIN SIZE:", result["model"]["domain_size"])
print("--- STDOUT ---")
print(result.get("complete_output", "N/A"))
