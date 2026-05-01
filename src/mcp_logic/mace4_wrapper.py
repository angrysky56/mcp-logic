"""
Mace4 model finder wrapper for counterexample finding and model generation.

Mace4 is a finite model finder that searches for finite models and counterexamples
to theorems. It's particularly useful when a proof attempt fails - Mace4 can often
find a counterexample showing why the statement isn't universally true.
"""

import asyncio
import logging
import os
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
                raise FileNotFoundError(
                    f"Mace4 not found at {self.mace4_exe} or with .exe extension"
                )

        logger.debug("Initialized Mace4 wrapper with Mace4 at %s", self.mace4_exe)

    def _create_input_file(
        self,
        premises: List[str],
        goal: Optional[str] = None,
        domain_size: Optional[int] = None,
    ) -> Path:
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

        # Goal (for counterexamples) — Mace4's formulas(goals) block auto-negates
        # and Skolemizes the goal internally (producing deny(N) clauses with
        # Skolem constants), exactly like Prover9.  Pass it through as-is.
        if goal:
            content.append("formulas(goals).")
            clean_goal = goal.rstrip(".")
            content.append(clean_goal + ".")
            content.append("end_of_list.")

        input_content = "\n".join(content)
        logger.debug("Created Mace4 input file content:\n%s", input_content)

        fd, path = tempfile.mkstemp(suffix=".in", text=True)
        with os.fdopen(fd, "w") as f:
            f.write(input_content)
        return Path(path)

    async def _run_mace4(self, input_path: Path, timeout: int = 60) -> Dict[str, Any]:
        """Run Mace4 model finder

        Args:
            input_path: Path to input file
            timeout: Timeout in seconds

        Returns:
            Dictionary with result, model details, and output
        """
        try:
            logger.debug("Running Mace4 with input file: %s", input_path)

            # Set working directory to Mace4 directory
            cwd = str(self.mace4_exe.parent)

            # Start the process
            process = await asyncio.create_subprocess_exec(
                str(self.mace4_exe),
                "-f",
                str(input_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                # Wait for completion with timeout
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
                stdout_str = stdout.decode()
                stderr_str = stderr.decode()

                logger.debug("Mace4 stdout:\n%s", stdout_str)
                if stderr_str:
                    logger.debug("Mace4 stderr:\n%s", stderr_str)

                # Parse Mace4 output
                if "DOMAIN SIZE" in stdout_str and "interpretation(" in stdout_str:
                    # Model found!
                    model = self._parse_model(stdout_str)
                    return {
                        "result": "model_found",
                        "model": model,
                        "complete_output": stdout_str,
                    }
                elif "SEARCH FAILED" in stdout_str or "SEARCH TERMINATED" in stdout_str:
                    return {
                        "result": "no_model_found",
                        "reason": "No finite model found within domain size limits",
                        "complete_output": stdout_str,
                    }
                elif "Fatal error" in stderr_str or "Fatal error" in stdout_str:
                    return {
                        "result": "error",
                        "reason": "Syntax error or invalid input",
                        "error": stderr_str if stderr_str else stdout_str,
                    }
                else:
                    return {
                        "result": "unknown",
                        "reason": "Unexpected Mace4 output",
                        "output": stdout_str,
                        "error": stderr_str,
                    }

            except asyncio.TimeoutError:
                logger.error("Mace4 search timed out after %d seconds", timeout)
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass
                return {
                    "result": "timeout",
                    "reason": f"Model search exceeded {timeout} seconds",
                }

        except (OSError, ValueError) as e:
            logger.error("Mace4 error: %s", e)
            return {"result": "error", "reason": str(e)}
        finally:
            try:
                input_path.unlink()  # Clean up temp file
            except (FileNotFoundError, PermissionError, OSError):
                pass  # Temp file cleanup failed, not critical

    def _parse_model(self, output: str) -> Dict[str, Any]:
        """Parse Mace4 model output into structured format.

        Extracts domain size, predicates (from ``relation()``), functions
        (from ``function()``), and constants (zero-arity functions) into
        dedicated dicts.  The ``raw_interpretation`` field contains the
        full interpretation block exactly once — no duplicate lines.

        Args:
            output: Raw Mace4 output

        Returns:
            Structured model representation
        """
        model: Dict[str, Any] = {
            "domain_size": None,
            "predicates": {},
            "functions": {},
            "constants": {},
            "raw_interpretation": "",
        }

        # Extract domain size
        for line in output.split("\n"):
            if "DOMAIN SIZE" in line:
                try:
                    parts = line.strip("= ").split()
                    for i, part in enumerate(parts):
                        if part == "SIZE" and i + 1 < len(parts):
                            model["domain_size"] = int(parts[i + 1])
                            break
                        if part == "size" and i + 1 < len(parts):
                            model["domain_size"] = int(parts[i + 1].rstrip("."))
                            break
                except (ValueError, IndexError):
                    pass

        # Extract interpretation block (once — no duplication)
        if "interpretation(" in output:
            start = output.find("interpretation(")
            end = output.find("end_of_list", start)
            if end > start:
                interpretation = output[start : end + len("end_of_list")]
                model["raw_interpretation"] = interpretation.strip()

                # Parse relation() and function() entries into structured dicts
                self._extract_structured_entries(interpretation, model)

        return model

    @staticmethod
    def _extract_structured_entries(
        interpretation: str, model: Dict[str, Any]
    ) -> None:
        """Extract relation/function entries from an interpretation block.

        Populates ``model["predicates"]``, ``model["functions"]``, and
        ``model["constants"]`` in-place.

        Args:
            interpretation: The raw ``interpretation(...)`` block text.
            model: Model dict to populate.
        """
        import re

        # Patterns for Mace4 interpretation entries:
        #   relation(Name(_,...), [ values ])
        #   function(Name(_,...), [ values ])
        #   function(Name, [ value ])          (constant — zero-arity)
        entry_re = re.compile(
            r"(relation|function)\(\s*"
            r"([a-zA-Z_][a-zA-Z0-9_]*)"   # name
            r"(\([^)]*\))?"                # optional arity signature like "(_)" or "(_,_)"
            r"\s*,\s*\[\s*"
            r"([^\]]*)"                    # values inside [ ... ]
            r"\]"
        )

        for m in entry_re.finditer(interpretation):
            kind = m.group(1)       # "relation" or "function"
            name = m.group(2)       # predicate/function name
            arity_sig = m.group(3)  # e.g. "(_)" or None for constants
            raw_vals = m.group(4).strip()

            # Parse the comma-separated values
            values = [v.strip() for v in raw_vals.split(",") if v.strip()] if raw_vals else []

            if kind == "relation":
                model["predicates"][name] = values
            elif arity_sig is None or arity_sig.replace(" ", "") == "":
                # No arity signature → constant (zero-arity function)
                model["constants"][name] = values
            else:
                model["functions"][name] = values

    async def find_model(
        self, premises: List[str], domain_size: Optional[int] = None
    ) -> Dict[str, Any]:
        """Find a model that satisfies the given premises

        Args:
            premises: List of logical premises
            domain_size: Specific domain size, or None to search incrementally

        Returns:
            Result dictionary with model if found
        """
        input_file = self._create_input_file(
            premises, goal=None, domain_size=domain_size
        )
        return await self._run_mace4(input_file)

    async def find_counterexample(
        self, premises: List[str], conclusion: str, domain_size: Optional[int] = None
    ) -> Dict[str, Any]:
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
        input_file = self._create_input_file(
            premises, goal=conclusion, domain_size=domain_size
        )
        result = await self._run_mace4(input_file)

        # If we found a model, it's a counterexample
        if result["result"] == "model_found":
            result["interpretation"] = (
                f"Counterexample found: The premises are satisfied but "
                f"the conclusion '{conclusion}' is FALSE in this model."
            )

        return result
