"""
Mace4 model finder wrapper for counterexample finding and model generation.

Mace4 is a finite model finder that searches for finite models and counterexamples
to theorems. It's particularly useful when a proof attempt fails - Mace4 can often
find a counterexample showing why the statement isn't universally true.
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mcp_logic.mace4")


class Mace4Wrapper:
    """Wrapper for Mace4 model finder"""

    def __init__(self, mace4_path: Path):
        """Initialize Mace4 wrapper

        Args:
            mace4_path: Path to directory containing Mace4 binary
        """
        self.mace4_path = Path(mace4_path)

        # Try both mace4.exe (Windows) and mace4 (Linux/Mac)
        self.mace4_exe = self.mace4_path / "mace4.exe"
        if not self.mace4_exe.exists():
            self.mace4_exe = self.mace4_path / "mace4"
            if not self.mace4_exe.exists():
                raise FileNotFoundError(f"Mace4 not found at {self.mace4_exe} or with .exe extension")

        logger.debug(f"Initialized Mace4 wrapper with Mace4 at {self.mace4_exe}")

    def _create_input_file(self, premises: List[str], goal: Optional[str] = None, domain_size: Optional[int] = None) -> Path:
        """Create a Mace4 input file

        Args:
            premises: List of logical premises (assumptions)
            goal: Goal to disprove (for counterexamples). If None, find any model.
            domain_size: Maximum domain size to search. If None, Mace4 will increment.

        Returns:
            Path to created input file
        """
        content = []

        # Domain size configuration
        if domain_size is not None:
            content.append(f"assign(domain_size, {domain_size}).")
        else:
            content.append("assign(domain_size, 2).")  # Start at 2
            content.append("assign(end_size, 10).")  # Try up to size 10

        # Timeout
        content.append("assign(max_seconds, 60).")
        content.append("")

        # Premises (assumptions)
        content.append("formulas(assumptions).")
        for premise in premises:
            content.append(premise if premise.endswith(".") else premise + ".")
        content.append("end_of_list.")
        content.append("")

        # Goal (for counterexamples) - negate it to find models where it's false
        if goal:
            content.append("formulas(goals).")
            # Negate the goal - if Mace4 finds a model, the goal is false in that model
            negated_goal = f"-(({goal.rstrip('.')}))"
            content.append(negated_goal + ".")
            content.append("end_of_list.")

        input_content = "\n".join(content)
        logger.debug(f"Created Mace4 input file content:\n{input_content}")

        fd, path = tempfile.mkstemp(suffix=".in", text=True)
        with os.fdopen(fd, "w") as f:
            f.write(input_content)
        return Path(path)

    def _run_mace4(self, input_path: Path, timeout: int = 60) -> Dict[str, Any]:
        """Run Mace4 model finder

        Args:
            input_path: Path to input file
            timeout: Timeout in seconds

        Returns:
            Dictionary with result, model details, and output
        """
        try:
            logger.debug(f"Running Mace4 with input file: {input_path}")

            # Set working directory to Mace4 directory
            cwd = str(self.mace4_exe.parent)
            result = subprocess.run([str(self.mace4_exe), "-f", str(input_path)], capture_output=True, text=True, timeout=timeout, cwd=cwd)

            logger.debug(f"Mace4 stdout:\n{result.stdout}")
            if result.stderr:
                logger.debug(f"Mace4 stderr:\n{result.stderr}")

            # Parse Mace4 output
            if "DOMAIN SIZE" in result.stdout and "interpretation(" in result.stdout:
                # Model found!
                model = self._parse_model(result.stdout)
                return {"result": "model_found", "model": model, "complete_output": result.stdout}
            elif "SEARCH FAILED" in result.stdout or "SEARCH TERMINATED" in result.stdout:
                return {"result": "no_model_found", "reason": "No finite model found within domain size limits", "complete_output": result.stdout}
            elif "Fatal error" in result.stderr or "Fatal error" in result.stdout:
                return {"result": "error", "reason": "Syntax error or invalid input", "error": result.stderr if result.stderr else result.stdout}
            else:
                return {"result": "unknown", "reason": "Unexpected Mace4 output", "output": result.stdout, "error": result.stderr}

        except subprocess.TimeoutExpired:
            logger.error(f"Mace4 search timed out after {timeout} seconds")
            return {"result": "timeout", "reason": f"Model search exceeded {timeout} seconds"}
        except Exception as e:
            logger.error(f"Mace4 error: {e}")
            return {"result": "error", "reason": str(e)}
        finally:
            try:
                input_path.unlink()  # Clean up temp file
            except (FileNotFoundError, PermissionError, OSError):
                pass  # Temp file cleanup failed, not critical

    def _parse_model(self, output: str) -> Dict[str, Any]:
        """Parse Mace4 model output into structured format

        Args:
            output: Raw Mace4 output

        Returns:
            Structured model representation
        """
        model = {"domain_size": None, "predicates": {}, "functions": {}, "constants": {}, "raw_interpretation": ""}

        # Extract domain size
        for line in output.split("\n"):
            if "DOMAIN SIZE" in line:
                try:
                    size = int(line.split()[-1])
                    model["domain_size"] = size
                except:
                    pass

        # Extract interpretation block
        if "interpretation(" in output:
            start = output.find("interpretation(")
            end = output.find("end_of_list", start)
            if end > start:
                interpretation = output[start : end + len("end_of_list")]
                model["raw_interpretation"] = interpretation.strip()

                # Parse individual predicates and functions
                # This is a simplified parser - full Mace4 output can be complex
                for line in interpretation.split("\n"):
                    line = line.strip()
                    if line.startswith("function(") or line.startswith("relation("):
                        # Extract name and values
                        model["raw_interpretation"] += f"\n{line}"

        return model

    def find_model(self, premises: List[str], domain_size: Optional[int] = None) -> Dict[str, Any]:
        """Find a model that satisfies the given premises

        Args:
            premises: List of logical premises
            domain_size: Specific domain size, or None to search incrementally

        Returns:
            Result dictionary with model if found
        """
        input_file = self._create_input_file(premises, goal=None, domain_size=domain_size)
        return self._run_mace4(input_file)

    def find_counterexample(self, premises: List[str], conclusion: str, domain_size: Optional[int] = None) -> Dict[str, Any]:
        """Find a counterexample showing the conclusion doesn't follow from premises

        This searches for a model where all premises are true but the conclusion is false.
        If such a model is found, it proves the conclusion doesn't logically follow.

        Args:
            premises: List of logical premises
            conclusion: Conclusion to disprove
            domain_size: Specific domain size, or None to search incrementally

        Returns:
            Result dictionary with counterexample model if found
        """
        input_file = self._create_input_file(premises, goal=conclusion, domain_size=domain_size)
        result = self._run_mace4(input_file)

        # If we found a model, it's a counterexample
        if result["result"] == "model_found":
            result["interpretation"] = f"Counterexample found: The premises are satisfied but the conclusion '{conclusion}' is FALSE in this model."

        return result
