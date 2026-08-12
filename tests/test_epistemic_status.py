"""Unified epistemic status contract across solver backends."""

from mcp_logic.epistemic_status import EpistemicStatus, is_verified, with_status


def test_proof_and_counterexample_are_verified_decisions() -> None:
    proof = with_status({"result": "proved"}, operation="prove")
    counterexample = with_status(
        {"result": "model_found"}, operation="find_counterexample"
    )

    assert proof["status"] == "PROVED"
    assert counterexample["status"] == "REFUTED"
    assert is_verified(proof) is True
    assert is_verified(counterexample) is True


def test_bounded_exhaustion_and_resource_limits_are_not_verified() -> None:
    bounded = with_status({"result": "no_model_found"}, operation="find_model")
    stopped = with_status({"result": "timeout"}, operation="prove")

    assert bounded["status"] == EpistemicStatus.BOUNDED_NO_MODEL
    assert stopped["status"] == EpistemicStatus.RESOURCE_LIMIT
    assert is_verified(bounded) is False
    assert is_verified(stopped) is False


def test_context_licensed_status_is_not_downgraded_by_normalization() -> None:
    licensed = with_status(
        {"result": "no_model_found", "status": EpistemicStatus.PROVED},
        operation="find_counterexample",
    )

    assert licensed["status"] == EpistemicStatus.PROVED
    assert is_verified(licensed) is True
