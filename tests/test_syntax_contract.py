"""The syntax rules must not drift between their two consumers.

The onboard advisor gets them via its prompt; the calling agent reads them
from ``mcp_logic_agent.md``.  Previously each carried its own hand-written
copy.  These tests fail the moment the copies disagree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_logic.logic_advisor import _FORMALIZE_LINES_SYSTEM
from mcp_logic.syntax_contract import (
    PROVER9_SYNTAX_RULES,
    doc_block,
    extract_doc_block,
    sync_doc,
)

GUIDE = Path(__file__).resolve().parent.parent / "mcp_logic_agent.md"


def test_advisor_prompt_embeds_the_canonical_rules() -> None:
    assert PROVER9_SYNTAX_RULES in _FORMALIZE_LINES_SYSTEM


def test_prompt_has_no_unfilled_placeholder() -> None:
    assert "{syntax_rules}" not in _FORMALIZE_LINES_SYSTEM


@pytest.mark.skipif(not GUIDE.exists(), reason="agent guide not present")
def test_agent_guide_is_in_sync() -> None:
    block = extract_doc_block(GUIDE.read_text(encoding="utf-8"))
    assert block is not None, "generated markers missing from mcp_logic_agent.md"
    assert block == doc_block(), (
        "mcp_logic_agent.md is out of date — run "
        "`python -m mcp_logic.syntax_contract --sync`"
    )


def test_sync_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "guide.md"
    target.write_text(f"intro\n\n{doc_block()}\n\noutro\n", encoding="utf-8")
    assert sync_doc(target) is False


def test_sync_rewrites_a_stale_block(tmp_path: Path) -> None:
    target = tmp_path / "guide.md"
    stale = doc_block().replace("ASCII only", "anything goes")
    target.write_text(f"intro\n\n{stale}\n", encoding="utf-8")

    assert sync_doc(target) is True
    assert doc_block() in target.read_text(encoding="utf-8")


def test_missing_markers_are_an_error(tmp_path: Path) -> None:
    target = tmp_path / "guide.md"
    target.write_text("no markers here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        sync_doc(target)
