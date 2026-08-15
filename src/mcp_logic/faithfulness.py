"""Does the formalization actually say what the question asked?

Everything else in this package hardens the path from *formula* to
*verdict*: saturation vs resource limits, decidable fragments, honest
``unknown``. None of it touches the step from *question* to *formula*, and
that step fails silently. Two observed live failures, both returning
``status: REFUTED`` with a genuine machine-checked answer:

* "If x is an integer greater than 0, is 2x greater than x?" formalized
  with **no premises** — Z3 dutifully answered a different question and
  reported the counterexample ``x = 0``.
* "Does it follow that her age is over 50?" formalized with the goal
  **negated** — the verdict came out right, the justification incoherent.

The same class killed the Lean probe: a theorem stating "every number
greater than 2 is odd", the word *prime* quietly gone.

## What this module does and does not do

It gathers **evidence**, and deliberately does not render a verdict.

Measured on this model, back-translation is good but not reliable — it
reads ``all p (gt(p, two) -> odd(p))`` correctly, yet renders ``(> age 0)``
as "the age is not zero". A mistranslation used as a judgement would
produce false alarms, and worse, could rubber-stamp a bad formalization.
So the natural-language reading is surfaced for the *caller* to check,
alongside deterministic gaps that cannot mistranslate.

Nothing here changes ``EpistemicStatus``. A solver that decided is still a
solver that decided; what is in question is whether it was asked the right
thing, which is a different axis and belongs in its own field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Words that mark a question as conditional — "if P, does Q follow?".
#: A conditional question with no premises has lost its hypothesis.
_CONDITIONAL_MARKERS = re.compile(
    r"\b(if|given|assume|assuming|suppose|when|whenever|provided|since)\b",
    re.IGNORECASE,
)

#: Function words carry no formalizable content, so their absence from a
#: formalization means nothing.
#:
#: Three groups are suppressed beyond ordinary stopwords, each learned from
#: a false positive:
#:
#: * **Relational words rendered as operators.** "greater", "times" and
#:   friends become ``>`` and ``*``; demanding the word appear verbatim
#:   flags every correct arithmetic formalization.
#: * **Task vocabulary.** "formula", "tautology", "model" describe what to
#:   do with the content, and never appear inside it.
#: * **Type nouns.** "number", "integer" name sorts, which live in the
#:   ``variables`` map rather than the formulas.
_STOPWORDS = frozenset("""
    a an the and or not but is are was were be been being do does did done
    have has had it its this that these those there here what which who whom
    whose when where why how if then else than as of to in on at by for with
    from into about over under again further once all any both each few more
    most other some such only own same so too very can will just should now
    follow follows following true false question answer prove proven
    show shows showing given assume assuming suppose whether every
    number numbers integer integers real reals value values thing things
    greater less larger smaller bigger fewer above below over under
    times plus minus divided multiplied equal equals equalling
    divisible divides sum product difference quotient remainder between
    element elements domain member members entity entities own itself
    formula formulas tautology contradiction contingent satisfiable
    model models world worlds logic logical statement statements
    premise premises conclusion conclusions axiom axioms theorem
    find check verify test determine decide compute
    """.split())

#: Digits matter: "greater than 0" losing its 0 is a dropped hypothesis.
#: Internal apostrophes and hyphens are kept so "well-formed" stays one
#: word, but a trailing possessive is trimmed — "Alice's" was being
#: reported as the nonexistent word "alice'".
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*[A-Za-z]|\d+")


@dataclass(frozen=True)
class FaithfulnessReport:
    """Evidence about whether a formalization matches its question.

    Attributes:
        reads_as: The formalization rendered back into English, or "" when
            back-translation was not run.
        warnings: Human-readable gaps found by deterministic checks.
        checked: Whether any check actually ran.
    """

    reads_as: str = ""
    warnings: list[str] = field(default_factory=list)
    checked: bool = False

    @property
    def looks_suspicious(self) -> bool:
        """Whether any deterministic gap was found."""
        return bool(self.warnings)

    def to_dict(self) -> dict[str, Any]:
        """Render for the MCP response."""
        return {
            "reads_as": self.reads_as,
            "warnings": self.warnings,
            "checked": self.checked,
            "note": (
                "Evidence only. A solver verdict certifies that the "
                "FORMALIZATION was decided, not that the formalization "
                "matches the question. Compare 'reads_as' against what you "
                "asked."
            ),
        }


def plan_formula_text(plan: dict[str, Any]) -> str:
    """Concatenate every formula-bearing field of a plan into one string."""
    parts: list[str] = []
    for key in ("premises", "statements", "constraints"):
        value = plan.get(key)
        if isinstance(value, list):
            parts.extend(str(v) for v in value)
    for key in ("conclusion", "formula"):
        value = plan.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    variables = plan.get("variables")
    if isinstance(variables, dict):
        parts.extend(variables)
    return " ".join(parts)


def stem(word: str) -> str:
    """Crudely singularise so ``cats`` matches the predicate ``cat``.

    A deliberately shallow stemmer: the goal is only to stop plurals in the
    question from looking absent from singular predicate names.
    """
    lowered = word.lower()
    # Possessives first: "alice's" must become "alice", not "alice'".
    if lowered.endswith("'s"):
        lowered = lowered[:-2]
    lowered = lowered.rstrip("'")
    for suffix in ("ies", "es", "s"):
        if len(lowered) > len(suffix) + 2 and lowered.endswith(suffix):
            return lowered[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return lowered


def content_words(text: str) -> set[str]:
    """Extract lowercase content stems and numerals from ``text``."""
    words: set[str] = set()
    for raw in _WORD_RE.findall(text):
        lowered = raw.lower()
        if lowered in _STOPWORDS:
            continue
        stemmed = stem(lowered)
        if stemmed in _STOPWORDS:
            continue
        words.add(stemmed if not lowered.isdigit() else lowered)
    return words


def coverage_gaps(question: str, plan: dict[str, Any]) -> list[str]:
    """Content words in the question with no trace in the formalization.

    A word that names something the question is *about* — ``prime``,
    ``0`` — should appear somewhere in the formulas, as a predicate name, a
    constant or a numeral. Its total absence is the signature of a dropped
    hypothesis.

    Substring matching is used on purpose: ``prime`` should match
    ``is_prime`` and ``primes``. This is a warning, not a verdict, so the
    cost of a near-miss is low and the cost of a miss is high.

    Args:
        question: The original natural-language question.
        plan: The formalization plan.

    Returns:
        Warning strings, one per uncovered word (capped for readability).
    """
    formal = plan_formula_text(plan).lower()
    if not formal:
        return []

    def covered(word: str) -> bool:
        if word in formal:
            return True
        # Predicates are routinely abbreviated — "successor" becomes
        # `succ(x,y)` — so a shared prefix counts as coverage. Erring
        # towards silence is deliberate: a warning nobody trusts is worse
        # than a warning that occasionally misses.
        return len(word) >= 4 and word[:4] in formal

    missing = sorted(word for word in content_words(question) if not covered(word))
    # Words shorter than four characters are too noisy to report, except
    # numerals, where a missing "0" or "50" is exactly the interesting case.
    reportable = [w for w in missing if len(w) >= 4 or w.isdigit()]
    return [
        f"'{word}' appears in the question but nowhere in the formalization"
        for word in reportable[:6]
    ]


def premise_gap(question: str, plan: dict[str, Any]) -> list[str]:
    """A conditional question formalized without any premises.

    "If x is greater than 0, is 2x greater than x?" carries a hypothesis.
    Formalizing it with an empty premise list asks an unconditional
    question instead — and the solver will answer that one, confidently.
    """
    if not _CONDITIONAL_MARKERS.search(question):
        return []
    if plan.get("tool") in {"check_contingency", "check_well_formed", "none"}:
        return []

    premises = plan.get("premises") or plan.get("constraints") or []
    if premises:
        return []
    return [
        "the question states a condition ('if'/'given'/'assume') but the "
        "formalization has no premises — the hypothesis may have been dropped"
    ]


def assess(
    question: str, plan: dict[str, Any], reads_as: str = ""
) -> FaithfulnessReport:
    """Collect faithfulness evidence for a formalization.

    Args:
        question: The original natural-language question.
        plan: The formalization plan handed to a solver.
        reads_as: Optional back-translation of the plan into English.

    Returns:
        A :class:`FaithfulnessReport`. Never raises; an unusable plan
        simply yields no warnings.
    """
    if not isinstance(plan, dict) or plan.get("tool") in (None, "none"):
        return FaithfulnessReport(reads_as=reads_as, checked=False)

    warnings = [*premise_gap(question, plan), *coverage_gaps(question, plan)]
    return FaithfulnessReport(reads_as=reads_as, warnings=warnings, checked=True)
