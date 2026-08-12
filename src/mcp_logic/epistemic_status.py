"""One vocabulary for what a solver result actually establishes."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


class EpistemicStatus(str, Enum):
    """Machine-readable strength of a solver result."""

    PROVED = "PROVED"
    REFUTED = "REFUTED"
    SATURATED_NO_PROOF = "SATURATED_NO_PROOF"
    BOUNDED_NO_MODEL = "BOUNDED_NO_MODEL"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    MALFORMED = "MALFORMED"


VERIFIED_STATUSES = frozenset(
    {
        EpistemicStatus.PROVED,
        EpistemicStatus.REFUTED,
        EpistemicStatus.SATURATED_NO_PROOF,
    }
)


def is_verified(result: Mapping[str, Any]) -> bool:
    """Return whether ``result`` contains a machine-checked verdict."""

    try:
        status = EpistemicStatus(result.get("status"))
    except (TypeError, ValueError):
        return False
    return status in VERIFIED_STATUSES


def with_status(result: Mapping[str, Any], *, operation: str) -> dict[str, Any]:
    """Return a result carrying the status implied by its operation and outcome.

    Existing ``result`` strings remain intact for API compatibility.  Callers
    must use ``status`` for epistemic decisions.
    """

    annotated = dict(result)
    try:
        annotated["status"] = EpistemicStatus(annotated.get("status"))
    except (TypeError, ValueError):
        pass
    else:
        return annotated

    outcome = annotated.get("result")

    if outcome == "proved":
        status = EpistemicStatus.PROVED
    elif outcome == "unprovable":
        status = EpistemicStatus.SATURATED_NO_PROOF
    elif outcome in {"counterexample"}:
        status = EpistemicStatus.REFUTED
    elif outcome == "model_found":
        status = (
            EpistemicStatus.REFUTED
            if operation == "find_counterexample"
            else EpistemicStatus.PROVED
        )
    elif outcome == "no_model_found":
        status = EpistemicStatus.BOUNDED_NO_MODEL
    elif outcome == "satisfiable":
        status = EpistemicStatus.PROVED
    elif outcome == "unsatisfiable":
        status = EpistemicStatus.REFUTED
    elif outcome in {"unknown", "inconclusive", "timeout"}:
        status = EpistemicStatus.RESOURCE_LIMIT
    elif outcome == "error" or annotated.get("validation_error"):
        status = EpistemicStatus.MALFORMED
    elif "valid" in annotated:
        status = (
            EpistemicStatus.PROVED
            if annotated.get("valid")
            else EpistemicStatus.MALFORMED
        )
    elif operation == "check_contingency" and "is_contingent" in annotated:
        status = EpistemicStatus.PROVED
    else:
        status = EpistemicStatus.RESOURCE_LIMIT

    annotated["status"] = status
    return annotated
