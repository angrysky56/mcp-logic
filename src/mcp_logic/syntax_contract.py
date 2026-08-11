"""The single source of truth for Prover9/Mace4 formula syntax.

Two very different consumers need these rules and must not disagree:

* the **onboard advisor model**, which gets them inside its formalization
  system prompt, and
* the **calling agent** (Claude and friends), which reads them from
  ``mcp_logic_agent.md``.

They were previously written out separately in each place, in different
words, free to drift apart with nothing to catch it.  Now the prompt
imports :data:`PROVER9_SYNTAX_RULES` and the guide embeds it between
marker comments, with ``tests/test_syntax_contract.py`` failing if the two
copies diverge.

To change the rules: edit here, run
``python -m mcp_logic.syntax_contract --sync`` to update the guide.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: Marker comments delimiting the generated block in the agent guide.
DOC_BEGIN = "<!-- BEGIN GENERATED: prover9-syntax -->"
DOC_END = "<!-- END GENERATED: prover9-syntax -->"

#: The canonical rules. Keep every line short enough to read in a prompt.
PROVER9_SYNTAX_RULES = """\
- ASCII only. Never use Unicode logic symbols.
- Universal: all x (human(x) -> mortal(x))
- Existential: exists x (pet(x) & dog(x))
- Connectives: -> implies, <-> iff, & and, | or, - not
- Predicates, functions and constants are lowercase: human(x), socrates
- Variables are lowercase letters: x, y, z
- Equality =, inequality !=
- Quantifiers MUST be parenthesized, and scope explicitly:
  all x (man(x) -> (exists y (father(y, x))))
- No trailing period on a formula.
- A predicate must take the SAME number of arguments everywhere it appears.\
"""


def doc_block() -> str:
    """The rules wrapped in the markers used inside the agent guide."""
    return f"{DOC_BEGIN}\n\n{PROVER9_SYNTAX_RULES}\n\n{DOC_END}"


def extract_doc_block(markdown: str) -> str | None:
    """Pull the generated block out of ``markdown``.

    Args:
        markdown: Full text of the agent guide.

    Returns:
        The block including its markers, or ``None`` if absent.
    """
    start = markdown.find(DOC_BEGIN)
    end = markdown.find(DOC_END)
    if start == -1 or end == -1:
        return None
    return markdown[start : end + len(DOC_END)]


def sync_doc(path: Path) -> bool:
    """Rewrite the generated block in the agent guide.

    Args:
        path: Path to ``mcp_logic_agent.md``.

    Returns:
        True if the file changed.

    Raises:
        ValueError: If the marker comments are missing.
    """
    text = path.read_text(encoding="utf-8")
    existing = extract_doc_block(text)
    if existing is None:
        raise ValueError(
            f"{path} is missing the {DOC_BEGIN} / {DOC_END} markers; "
            "add them where the syntax rules belong."
        )
    if existing == doc_block():
        return False
    path.write_text(text.replace(existing, doc_block()), encoding="utf-8")
    return True


def _main() -> int:
    guide = Path(__file__).resolve().parents[2] / "mcp_logic_agent.md"
    if "--sync" in sys.argv:
        changed = sync_doc(guide)
        print(f"{'updated' if changed else 'already current'}: {guide}")
        return 0
    print(PROVER9_SYNTAX_RULES)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
