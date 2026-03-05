"""Tests for the propositional formula AST, parser, and utilities."""

import pytest

from mcp_logic.formula_ast import (
    And,
    Not,
    Or,
    ParseError,
    Var,
    are_complementary,
    atoms,
    complexity,
    is_literal,
    negate,
    parse,
    to_nnf,
)

# ---------------------------------------------------------------------------
# Parsing Tests
# ---------------------------------------------------------------------------


class TestParsing:
    """Tests for the recursive descent parser."""

    def test_parse_single_variable(self) -> None:
        assert parse("p") == Var("p")

    def test_parse_negation(self) -> None:
        assert parse("~p") == Not(Var("p"))

    def test_parse_dash_negation(self) -> None:
        assert parse("-p") == Not(Var("p"))

    def test_parse_conjunction(self) -> None:
        assert parse("p & q") == And(Var("p"), Var("q"))

    def test_parse_disjunction(self) -> None:
        assert parse("p | q") == Or(Var("p"), Var("q"))

    def test_parse_precedence_and_binds_tighter(self) -> None:
        # p | q & r  should be  p | (q & r)
        result = parse("p | q & r")
        assert result == Or(Var("p"), And(Var("q"), Var("r")))

    def test_parse_parentheses_override_precedence(self) -> None:
        result = parse("(p | q) & r")
        assert result == And(Or(Var("p"), Var("q")), Var("r"))

    def test_parse_nested_negation(self) -> None:
        result = parse("~~p")
        assert result == Not(Not(Var("p")))

    def test_parse_complex_formula(self) -> None:
        result = parse("(p & (q | r)) & (r | q)")
        expected = And(
            And(Var("p"), Or(Var("q"), Var("r"))),
            Or(Var("r"), Var("q")),
        )
        assert result == expected

    def test_parse_paper_example(self) -> None:
        """Example 4 from the paper: ((p & (q | r)) & (r | q)) | p."""
        result = parse("((p & (q | r)) & (r | q)) | p")
        expected = Or(
            And(
                And(Var("p"), Or(Var("q"), Var("r"))),
                Or(Var("r"), Var("q")),
            ),
            Var("p"),
        )
        assert result == expected

    def test_parse_whitespace_tolerance(self) -> None:
        assert parse("  p  &  q  ") == And(Var("p"), Var("q"))

    def test_parse_error_on_empty(self) -> None:
        with pytest.raises(ParseError):
            parse("")

    def test_parse_error_on_invalid_char(self) -> None:
        with pytest.raises(ParseError):
            parse("p @ q")

    def test_parse_error_on_unmatched_paren(self) -> None:
        with pytest.raises(ParseError):
            parse("(p & q")

    def test_parse_multichar_var(self) -> None:
        result = parse("foo & bar")
        assert result == And(Var("foo"), Var("bar"))

    def test_parse_left_associativity_and(self) -> None:
        result = parse("p & q & r")
        assert result == And(And(Var("p"), Var("q")), Var("r"))

    def test_parse_left_associativity_or(self) -> None:
        result = parse("p | q | r")
        assert result == Or(Or(Var("p"), Var("q")), Var("r"))


# ---------------------------------------------------------------------------
# NNF Conversion Tests
# ---------------------------------------------------------------------------


class TestNNF:
    """Tests for Negation Normal Form conversion."""

    def test_nnf_variable(self) -> None:
        assert to_nnf(Var("p")) == Var("p")

    def test_nnf_literal(self) -> None:
        assert to_nnf(Not(Var("p"))) == Not(Var("p"))

    def test_nnf_double_negation(self) -> None:
        assert to_nnf(Not(Not(Var("p")))) == Var("p")

    def test_nnf_de_morgan_and(self) -> None:
        # ~(p & q) → ~p | ~q
        f = Not(And(Var("p"), Var("q")))
        result = to_nnf(f)
        assert result == Or(Not(Var("p")), Not(Var("q")))

    def test_nnf_de_morgan_or(self) -> None:
        # ~(p | q) → ~p & ~q
        f = Not(Or(Var("p"), Var("q")))
        result = to_nnf(f)
        assert result == And(Not(Var("p")), Not(Var("q")))

    def test_nnf_nested(self) -> None:
        # ~(~p & q) → p | ~q
        f = Not(And(Not(Var("p")), Var("q")))
        result = to_nnf(f)
        assert result == Or(Var("p"), Not(Var("q")))

    def test_nnf_deeply_nested(self) -> None:
        # ~~(p & ~q) → p & ~q
        f = Not(Not(And(Var("p"), Not(Var("q")))))
        result = to_nnf(f)
        assert result == And(Var("p"), Not(Var("q")))

    def test_nnf_idempotent(self) -> None:
        """Applying NNF to an already-NNF formula should be identity."""
        f = And(Not(Var("p")), Or(Var("q"), Not(Var("r"))))
        assert to_nnf(f) == f


# ---------------------------------------------------------------------------
# Utility Tests
# ---------------------------------------------------------------------------


class TestUtilities:
    """Tests for utility functions."""

    def test_complexity_var(self) -> None:
        assert complexity(Var("p")) == 1

    def test_complexity_not(self) -> None:
        assert complexity(Not(Var("p"))) == 2

    def test_complexity_binary(self) -> None:
        assert complexity(And(Var("p"), Var("q"))) == 3

    def test_complexity_nested(self) -> None:
        f = Or(And(Var("p"), Var("q")), Not(Var("r")))
        # Or(And(p, q), Not(r)) = 1 + (1 + 1 + 1) + (1 + 1) = 6
        assert complexity(f) == 6

    def test_atoms_single(self) -> None:
        assert atoms(Var("p")) == frozenset({"p"})

    def test_atoms_negated(self) -> None:
        assert atoms(Not(Var("p"))) == frozenset({"p"})

    def test_atoms_compound(self) -> None:
        f = And(Or(Var("p"), Var("q")), Not(Var("r")))
        assert atoms(f) == frozenset({"p", "q", "r"})

    def test_atoms_repeated(self) -> None:
        f = And(Var("p"), Var("p"))
        assert atoms(f) == frozenset({"p"})

    def test_is_literal_var(self) -> None:
        assert is_literal(Var("p")) is True

    def test_is_literal_negated_var(self) -> None:
        assert is_literal(Not(Var("p"))) is True

    def test_is_literal_compound(self) -> None:
        assert is_literal(And(Var("p"), Var("q"))) is False

    def test_is_literal_double_neg(self) -> None:
        assert is_literal(Not(Not(Var("p")))) is False

    def test_negate_var(self) -> None:
        assert negate(Var("p")) == Not(Var("p"))

    def test_negate_negation(self) -> None:
        assert negate(Not(Var("p"))) == Var("p")

    def test_are_complementary_positive(self) -> None:
        assert are_complementary(Var("p"), Not(Var("p"))) is True

    def test_are_complementary_reversed(self) -> None:
        assert are_complementary(Not(Var("p")), Var("p")) is True

    def test_are_complementary_different_vars(self) -> None:
        assert are_complementary(Var("p"), Not(Var("q"))) is False

    def test_are_complementary_same_var(self) -> None:
        assert are_complementary(Var("p"), Var("p")) is False


# ---------------------------------------------------------------------------
# String Representation Tests
# ---------------------------------------------------------------------------


class TestStringRepresentation:
    """Tests for __str__ methods on AST nodes."""

    def test_str_var(self) -> None:
        assert str(Var("p")) == "p"

    def test_str_not(self) -> None:
        assert str(Not(Var("p"))) == "~p"

    def test_str_and(self) -> None:
        assert str(And(Var("p"), Var("q"))) == "p & q"

    def test_str_or(self) -> None:
        assert str(Or(Var("p"), Var("q"))) == "p | q"

    def test_str_nested_adds_parens(self) -> None:
        f = And(Or(Var("p"), Var("q")), Var("r"))
        assert str(f) == "(p | q) & r"
