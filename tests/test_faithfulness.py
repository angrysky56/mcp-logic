"""Detecting formalizations that answer a different question.

A solver verdict certifies that the *formalization* was decided. It has
never certified that the formalization is the question you asked. Two live
failures motivated this file, both returning a genuine machine-checked
answer to something nobody asked:

* a conditional question formalized with **no premises**;
* the Lean probe's theorem that quietly dropped *prime*.

The detector must earn its place by being quiet on correct
formalizations — a warning that fires on everything is ignored on
everything, which is how the first version of this check behaved (6 of 6
flagged, including all the good ones).
"""

from __future__ import annotations

import pytest

from mcp_logic.faithfulness import assess, content_words, stem

# (question, plan) pairs that are faithful and must NOT be flagged.
FAITHFUL: list[tuple[str, dict]] = [
    (
        "If x is an integer greater than 0, is 2 times x greater than x?",
        {
            "tool": "prove_arithmetic",
            "premises": ["(> x 0)"],
            "conclusion": "(> (* 2 x) x)",
            "variables": {"x": "Int"},
        },
    ),
    (
        "All humans are mortal. Socrates is a human. Is Socrates mortal?",
        {
            "tool": "prove",
            "premises": ["all x (human(x) -> mortal(x))", "human(socrates)"],
            "conclusion": "mortal(socrates)",
        },
    ),
    (
        "All cats are animals. Some animals are dogs. "
        "Does it follow that some cats are dogs?",
        {
            "tool": "prove",
            "premises": [
                "all x (cat(x) -> animal(x))",
                "exists x (animal(x) & dog(x))",
            ],
            "conclusion": "exists x (cat(x) & dog(x))",
        },
    ),
    (
        "Is the formula p or not p a tautology?",
        {"tool": "check_contingency", "formula": "p | -p"},
    ),
    (
        "Find a world where every element has a successor and no element "
        "is its own successor.",
        {
            "tool": "find_model",
            "premises": ["all x exists y (succ(x,y))", "all x (-succ(x,x))"],
        },
    ),
    (
        "Is there an integer between 0 and 10 that is divisible by 3?",
        {
            "tool": "check_satisfiable",
            "constraints": ["(> n 0)", "(< n 10)", "(= (mod n 3) 0)"],
            "variables": {"n": "Int"},
        },
    ),
]


class TestQuietOnFaithfulWork:
    """Precision first: a noisy detector is a disabled detector."""

    @pytest.mark.parametrize(("question", "plan"), FAITHFUL)
    def test_no_warnings(self, question: str, plan: dict) -> None:
        report = assess(question, plan)
        assert not report.looks_suspicious, report.warnings


class TestCatchesObservedFailures:
    """The two failures that actually happened, plus the Lean one."""

    def test_dropped_premise_from_conditional_question(self) -> None:
        # Observed live: Z3 answered the unconditional question and
        # reported the counterexample x = 0.
        report = assess(
            "If x is an integer greater than 0, is 2 times x greater than x?",
            {
                "tool": "prove_arithmetic",
                "premises": [],
                "conclusion": "(> (* 2 x) x)",
                "variables": {"x": "Int"},
            },
        )
        assert report.looks_suspicious
        assert any("no premises" in w for w in report.warnings)

    def test_dropped_hypothesis_is_named(self) -> None:
        # The Lean probe wrote "every number greater than 2 is odd",
        # silently losing primality. The statement is false as written.
        report = assess(
            "Is every prime number greater than 2 odd?",
            {
                "tool": "prove",
                "premises": ["all p (gt(p, two) -> odd(p))"],
                "conclusion": "odd(p)",
            },
        )
        assert report.looks_suspicious
        assert any("prime" in w for w in report.warnings)

    def test_missing_numeral_is_reported(self) -> None:
        report = assess(
            "Given that the count is at least 5, is it at least 3?",
            {"tool": "prove_arithmetic", "premises": [], "conclusion": "(>= c 3)"},
        )
        assert report.looks_suspicious


class TestStemming:
    """Plurals in prose must match singular predicate names."""

    @pytest.mark.parametrize(
        ("word", "expected"),
        [("cats", "cat"), ("animals", "animal"), ("dogs", "dog"), ("cat", "cat")],
    )
    def test_stem(self, word: str, expected: str) -> None:
        assert stem(word) == expected

    def test_numerals_survive_untouched(self) -> None:
        assert "50" in content_words("is her age over 50")

    def test_possessive_is_trimmed(self) -> None:
        # "Alice's" was being reported as the nonexistent word "alice'".
        words = content_words("Alice's age is greater than 0")
        assert "alice" in words
        assert not any(w.endswith("'") for w in words)

    def test_hyphenated_word_stays_whole(self) -> None:
        assert "well-formed" in content_words("is the formula well-formed")


class TestReportShape:
    """The report is evidence, not a verdict."""

    def test_unformalizable_plan_is_not_checked(self) -> None:
        report = assess("what is your favourite colour?", {"tool": "none"})
        assert report.checked is False
        assert report.looks_suspicious is False

    def test_reads_as_is_carried_through(self) -> None:
        report = assess(
            "All humans are mortal. Is Socrates mortal?",
            {
                "tool": "prove",
                "premises": ["all x (human(x) -> mortal(x))"],
                "conclusion": "mortal(socrates)",
            },
            reads_as="Every human is mortal. Socrates is mortal.",
        )
        assert "Every human is mortal" in report.reads_as

    def test_dict_carries_the_caveat(self) -> None:
        payload = assess("Is p or not p a tautology?", {"tool": "none"}).to_dict()
        assert "does not" in payload["note"] or "not that" in payload["note"]
