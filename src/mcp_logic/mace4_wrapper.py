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
from typing import Any

from mcp_logic.syntax_validator import normalize_formula

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
        premises: list[str],
        goal: str | None = None,
        domain_size: int | None = None,
        timeout: int = 60,
    ) -> Path:
        """Create a Mace4 input file

        Args:
            premises: List of logical premises (assumptions)
            goal: Goal to disprove (for counterexamples). If None, find any model.
            domain_size: Maximum domain size to search. If None, Mace4 will increment.
            timeout: Maximum search time in seconds.

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
        content.append(f"assign(max_seconds, {timeout}).")
        content.append("")

        # Premises (assumptions)
        content.append("formulas(assumptions).")
        for premise in premises:
            p = normalize_formula(premise)
            content.append(p if p.endswith(".") else p + ".")
        content.append("end_of_list.")
        content.append("")

        # Goal (for counterexamples) — Mace4's formulas(goals) block auto-negates
        # and Skolemizes the goal internally (producing deny(N) clauses with
        # Skolem constants), exactly like Prover9.  Pass it through as-is.
        if goal:
            content.append("formulas(goals).")
            clean_goal = normalize_formula(goal).rstrip(".")
            content.append(clean_goal + ".")
            content.append("end_of_list.")

        input_content = "\n".join(content)
        logger.debug("Created Mace4 input file content:\n%s", input_content)

        fd, path = tempfile.mkstemp(suffix=".in", text=True)
        with os.fdopen(fd, "w") as f:
            f.write(input_content)
        return Path(path)

    async def _run_mace4(
        self, input_path: Path, timeout: int = 60, verbose: bool = False
    ) -> dict[str, Any]:
        """Run Mace4 model finder

        Args:
            input_path: Path to input file
            timeout: Timeout in seconds
            verbose: When True, include the full raw Mace4 output under
                ``complete_output``.  Default False returns only the parsed,
                structured model to keep responses compact.

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
                # Wait for completion with timeout (add 1s buffer for Mace4's internal timeout)
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout + 1
                )
                stdout_str = stdout.decode()
                stderr_str = stderr.decode()

                logger.debug("Mace4 stdout:\n%s", stdout_str)
                if stderr_str:
                    logger.debug("Mace4 stderr:\n%s", stderr_str)

                # Parse Mace4 output.
                #
                # Key on Mace4's authoritative exit-status line ("... exit (X)")
                # rather than fragile substring matches. The previous code tested
                # `"max_sec" in stdout_str`, but every input file echoes
                # `assign(max_seconds, N)`, so a clean exhaustion (no model) was
                # mislabeled as a timeout. Mace4's real signals are:
                #   exit (max_models) + interpretation(...)  -> model found
                #   exit (exhausted) / "Exiting with failure" -> no model exists
                #   exit (max_seconds)                        -> genuine timeout
                combined = stdout_str + "\n" + stderr_str
                model_found = (
                    "interpretation(" in stdout_str and "DOMAIN SIZE" in stdout_str
                )
                exhausted = (
                    "exit (exhausted)" in combined
                    or "Exiting with failure" in combined
                    or "SEARCH FAILED" in stdout_str
                    or "SEARCH TERMINATED" in stdout_str
                )
                hit_time_limit = (
                    "exit (max_seconds)" in combined
                    or "exit (max_megs)" in combined
                )

                if model_found:
                    # Model found!
                    model = self._parse_model(stdout_str)
                    result = {
                        "result": "model_found",
                        "model": model,
                    }
                    if verbose:
                        result["complete_output"] = stdout_str
                    return result
                elif exhausted:
                    result = {
                        "result": "no_model_found",
                        "reason": "Mace4 exhausted the search space up to the domain-size bound; no finite model exists.",
                    }
                    if verbose:
                        result["complete_output"] = stdout_str
                    return result
                elif hit_time_limit:
                    return {
                        "result": "timeout",
                        "reason": f"Model search exceeded {timeout} seconds (Mace4 internal limit).",
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

    def _parse_model(self, output: str) -> dict[str, Any]:
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
        model: dict[str, Any] = {
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

        # Extract interpretation block (once — no duplication).
        #
        # Mace4 model output is a single ``interpretation(...)`` statement
        # terminated by ``]).`` — it does NOT contain ``end_of_list`` (that
        # token only appears in *input* formula lists).  The earlier code
        # searched for ``end_of_list`` as the terminator, never found it, and
        # so left predicates/functions/constants empty on real Mace4 output.
        # We now terminate on the ``])`` that closes the value list + call.
        if "interpretation(" in output:
            start = output.find("interpretation(")
            end = output.find("]).", start)
            if end != -1:
                # Include the closing "])" of the interpretation call.
                interpretation = output[start : end + 2]
                model["raw_interpretation"] = interpretation.strip()

                # Parse relation() and function() entries into structured dicts
                self._extract_structured_entries(interpretation, model)

        return model

    @staticmethod
    def _extract_structured_entries(interpretation: str, model: dict[str, Any]) -> None:
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
            r"([a-zA-Z_][a-zA-Z0-9_]*)"  # name
            r"(\([^)]*\))?"  # optional arity signature like "(_)" or "(_,_)"
            r"\s*,\s*\[\s*"
            r"([^\]]*)"  # values inside [ ... ]
            r"\]"
        )

        for m in entry_re.finditer(interpretation):
            kind = m.group(1)  # "relation" or "function"
            name = m.group(2)  # predicate/function name
            arity_sig = m.group(3)  # e.g. "(_)" or None for constants
            raw_vals = m.group(4).strip()

            # Parse the comma-separated values
            values = (
                [v.strip() for v in raw_vals.split(",") if v.strip()]
                if raw_vals
                else []
            )

            if kind == "relation":
                model["predicates"][name] = values
            elif arity_sig is None or arity_sig.replace(" ", "") == "":
                # No arity signature → constant (zero-arity function)
                model["constants"][name] = values
            else:
                model["functions"][name] = values

    async def find_model(
        self,
        premises: list[str],
        domain_size: int | None = None,
        timeout: int = 60,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Find a model that satisfies the given premises

        Args:
            premises: List of logical premises
            domain_size: Specific domain size, or None to search incrementally
            timeout: Maximum search time in seconds
            verbose: Include raw Mace4 output when True.

        Returns:
            Result dictionary with model if found
        """
        input_file = self._create_input_file(
            premises, goal=None, domain_size=domain_size, timeout=timeout
        )
        return await self._run_mace4(input_file, timeout=timeout, verbose=verbose)

    async def find_counterexample(
        self,
        premises: list[str],
        conclusion: str,
        domain_size: int | None = None,
        timeout: int = 60,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Find a counterexample showing the conclusion doesn't follow from premises

        This searches for a model where all premises are true but the conclusion is false.
        If such a model is found, it proves the conclusion doesn't logically follow.

        Args:
            premises: List of logical premises
            conclusion: Conclusion to disprove
            domain_size: Specific domain size, or None to search incrementally
            timeout: Maximum search time in seconds

        Returns:
            Result dictionary with counterexample model if found
        """
        input_file = self._create_input_file(
            premises, goal=conclusion, domain_size=domain_size, timeout=timeout
        )
        result = await self._run_mace4(input_file, timeout=timeout, verbose=verbose)

        # If we found a model, it's a counterexample
        if result["result"] == "model_found":
            result["interpretation"] = (
                f"Counterexample found: The premises are satisfied but "
                f"the conclusion '{conclusion}' is FALSE in this model."
            )
        elif result["result"] == "no_model_found":
            # No counterexample exists within the search bounds — this is
            # *evidence for* (not proof of) the conclusion following.
            result["interpretation"] = (
                "No counterexample found within the domain-size bound. The "
                "conclusion may be valid — use the 'prove' tool to confirm it "
                "follows from the premises."
            )

        return result
