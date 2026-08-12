"""A failed proof search is not a refutation.

Prover9 prints ``SEARCH FAILED`` whether it exhausted the search space or
merely ran out of resources.  Collapsing both into "unprovable" turns a
shrug into a verdict: an argument abandoned on ``max_megs`` would be
reported as "the conclusion does not follow".

Only ``sos_empty`` — an emptied set of support, i.e. saturation — licenses
that claim, and it does so because resolution is refutation-complete.
Everything else is silence.  First-order validity is semi-decidable
(Harrison, *Handbook of Practical Logic and Automated Reasoning*, §7.6),
so there is no general way to turn "found no proof" into "there is no
proof".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_logic.server import _classify_search_failure

SATURATED = """\
============================== end of search ==========
SEARCH FAILED
Exiting with failure.
------ process 12345 exit (sos_empty) ------
"""

OUT_OF_TIME = """\
============================== end of search ==========
SEARCH FAILED
Exiting with failure.
------ process 12345 exit (max_seconds) ------
"""

OUT_OF_MEMORY = """\
SEARCH FAILED
------ process 12345 exit (max_megs) ------
"""


class TestSearchFailureClassification:
    """Saturation is a verdict; a resource limit is not."""

    def test_saturation_is_a_definitive_non_entailment(self) -> None:
        result = _classify_search_failure(SATURATED)
        assert result["result"] == "unprovable"
        assert result["status"] == "SATURATED_NO_PROOF"
        assert result["exit_reason"] == "sos_empty"
        assert "SATURATED" in result["reason"]

    @pytest.mark.parametrize(
        ("output", "expected_reason"),
        [(OUT_OF_TIME, "max_seconds"), (OUT_OF_MEMORY, "max_megs")],
    )
    def test_resource_limits_are_inconclusive(
        self, output: str, expected_reason: str
    ) -> None:
        result = _classify_search_failure(output)
        assert result["result"] == "inconclusive"
        assert result["status"] == "RESOURCE_LIMIT"
        assert result["exit_reason"] == expected_reason

    def test_inconclusive_does_not_claim_the_conclusion_is_false(self) -> None:
        reason = _classify_search_failure(OUT_OF_TIME)["reason"]
        assert "does not follow" not in reason
        assert "NOT evidence" in reason

    def test_unrecognised_output_is_inconclusive(self) -> None:
        # Fail safe: an exit reason we cannot parse must not be promoted
        # into a verdict.
        result = _classify_search_failure("SEARCH FAILED\n")
        assert result["result"] == "inconclusive"
        assert result["status"] == "RESOURCE_LIMIT"
        assert result["exit_reason"] == "unknown"


class TestAgainstRealProver9:
    """The saturation path must survive contact with the actual binary."""

    @pytest.fixture(scope="class")
    def engine(self) -> object:
        from mcp_logic.server import LogicEngine

        ladr = Path(__file__).resolve().parent.parent / "ladr" / "bin"
        if not (ladr / "prover9").exists():
            pytest.skip("LADR binaries are not built")
        return LogicEngine(str(ladr))

    @pytest.mark.asyncio
    async def test_invalid_argument_saturates(self, engine: object) -> None:
        # The classic invalid syllogism: Prover9 empties its sos list.
        path = engine.create_input_file(  # type: ignore[attr-defined]
            ["all x (cat(x) -> animal(x))", "exists x (animal(x) & dog(x))"],
            "exists x (cat(x) & dog(x))",
        )
        result = await engine.run_prover(path, timeout=30)  # type: ignore[attr-defined]

        assert result["result"] == "unprovable"
        assert result["status"] == "SATURATED_NO_PROOF"
        assert result["exit_reason"] == "sos_empty"

    @pytest.mark.asyncio
    async def test_valid_argument_still_proves(self, engine: object) -> None:
        path = engine.create_input_file(  # type: ignore[attr-defined]
            ["all x (human(x) -> mortal(x))", "human(socrates)"],
            "mortal(socrates)",
        )
        result = await engine.run_prover(path, timeout=30)  # type: ignore[attr-defined]
        assert result["result"] == "proved"
