"""
Propositional formula AST, parser, and utilities.

Provides immutable dataclasses for representing propositional logic formulas,
a recursive descent parser, Negation Normal Form (NNF) conversion, and
utility functions for complexity analysis and atom extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import FrozenSet, Union

# ---------------------------------------------------------------------------
# AST Node Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Var:
    """Atomic propositional variable (e.g., p, q, r)."""

    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class Not:
    """Negation of a formula."""

    inner: Formula

    def __str__(self) -> str:
        if isinstance(self.inner, Var):
            return f"~{self.inner}"
        return f"~({self.inner})"


@dataclass(frozen=True, slots=True)
class And:
    """Conjunction of two formulas."""

    left: Formula
    right: Formula

    def __str__(self) -> str:
        left_str = _paren_if_needed(self.left, And)
        right_str = _paren_if_needed(self.right, And)
        return f"{left_str} & {right_str}"


@dataclass(frozen=True, slots=True)
class Or:
    """Disjunction of two formulas."""

    left: Formula
    right: Formula

    def __str__(self) -> str:
        left_str = _paren_if_needed(self.left, Or)
        right_str = _paren_if_needed(self.right, Or)
        return f"{left_str} | {right_str}"


# Union type for all formula nodes
Formula = Union[Var, Not, And, Or]


def _paren_if_needed(f: Formula, parent_type: type) -> str:
    """Add parentheses around a sub-formula when needed for clarity."""
    if isinstance(f, (Var, Not)):
        return str(f)
    if parent_type is And and isinstance(f, Or):
        return f"({f})"
    if parent_type is Or and isinstance(f, And):
        return f"({f})"
    return str(f)


# ---------------------------------------------------------------------------
# Recursive Descent Parser
# ---------------------------------------------------------------------------

# Token types
# trunk-ignore(bandit/B105)
_TOKEN_VAR = "VAR"
# trunk-ignore(bandit/B105)
_TOKEN_NOT = "NOT"
# trunk-ignore(bandit/B105)
_TOKEN_AND = "AND"
# trunk-ignore(bandit/B105)
_TOKEN_OR = "OR"
# trunk-ignore(bandit/B105)
_TOKEN_IMPLIES = "IMPLIES"
# trunk-ignore(bandit/B105)
_TOKEN_IFF = "IFF"
# trunk-ignore(bandit/B105)
_TOKEN_LPAREN = "LPAREN"
# trunk-ignore(bandit/B105)
_TOKEN_RPAREN = "RPAREN"
# trunk-ignore(bandit/B105)
_TOKEN_EOF = "EOF"

_TOKEN_PATTERNS = [
    (r"\s+", None),  # skip whitespace
    (r"~|-(?!>)", _TOKEN_NOT),  # negation: ~ or - (not ->)
    (r"&|∧", _TOKEN_AND),  # conjunction
    (r"\||∨", _TOKEN_OR),  # disjunction
    (r"<->|↔", _TOKEN_IFF),  # bi-implication
    (r"->|→", _TOKEN_IMPLIES),  # implication
    (r"\(", _TOKEN_LPAREN),
    (r"\)", _TOKEN_RPAREN),
    (r"[a-zA-Z_][a-zA-Z0-9_]*", _TOKEN_VAR),  # variable names
]

_COMPILED_PATTERNS = [(re.compile(p), t) for p, t in _TOKEN_PATTERNS]


class ParseError(Exception):
    """Raised when formula parsing fails."""


def _tokenize(formula_str: str) -> list[tuple[str, str]]:
    """Tokenize a propositional formula string."""
    tokens: list[tuple[str, str]] = []
    pos = 0

    while pos < len(formula_str):
        matched = False
        for pattern, token_type in _COMPILED_PATTERNS:
            m = pattern.match(formula_str, pos)
            if m:
                if token_type is not None:
                    tokens.append((token_type, m.group()))
                pos = m.end()
                matched = True
                break
        if not matched:
            raise ParseError(
                f"Unexpected character '{formula_str[pos]}' " f"at position {pos}"
            )

    tokens.append((_TOKEN_EOF, ""))
    return tokens


class _Parser:
    """Recursive descent parser for propositional formulas.

    Grammar (precedence low → high):
        expr     := iff_expr
        iff_expr := impl_expr ( '<->' impl_expr )*
        impl_expr:= or_expr ( '->' or_expr )*
        or_expr  := and_expr ( '|' and_expr )*
        and_expr := not_expr ( '&' not_expr )*
        not_expr := '~' not_expr | atom
        atom     := VAR | '(' expr ')'
    """

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> str:
        return self.tokens[self.pos][0]

    def _advance(self) -> tuple[str, str]:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect(self, token_type: str) -> tuple[str, str]:
        if self._peek() != token_type:
            raise ParseError(
                f"Expected {token_type}, got {self._peek()} "
                f"('{self.tokens[self.pos][1]}')"
            )
        return self._advance()

    def parse(self) -> Formula:
        """Parse the full expression and ensure all input is consumed."""
        result = self._parse_iff()
        if self._peek() != _TOKEN_EOF:
            raise ParseError(
                f"Unexpected token after expression: " f"'{self.tokens[self.pos][1]}'"
            )
        return result

    def _parse_iff(self) -> Formula:
        left = self._parse_implies()
        while self._peek() == _TOKEN_IFF:
            self._advance()
            right = self._parse_implies()
            # A <-> B is (A -> B) & (B -> A)
            # Since we expand implies during conversion or here...
            # Let's expand here for simplicity.
            # A <-> B  =>  (~A | B) & (~B | A)
            a = left
            b = right
            left = And(Or(Not(a), b), Or(Not(b), a))
        return left

    def _parse_implies(self) -> Formula:
        left = self._parse_or()
        while self._peek() == _TOKEN_IMPLIES:
            self._advance()
            right = self._parse_or()
            # A -> B is ~A | B
            left = Or(Not(left), right)
        return left

    def _parse_or(self) -> Formula:
        left = self._parse_and()
        while self._peek() == _TOKEN_OR:
            self._advance()
            right = self._parse_and()
            left = Or(left, right)
        return left

    def _parse_and(self) -> Formula:
        left = self._parse_not()
        while self._peek() == _TOKEN_AND:
            self._advance()
            right = self._parse_not()
            left = And(left, right)
        return left

    def _parse_not(self) -> Formula:
        if self._peek() == _TOKEN_NOT:
            self._advance()
            inner = self._parse_not()
            return Not(inner)
        return self._parse_atom()

    def _parse_atom(self) -> Formula:
        if self._peek() == _TOKEN_VAR:
            tok = self._advance()
            return Var(tok[1])
        if self._peek() == _TOKEN_LPAREN:
            self._advance()
            expr = self._parse_iff()
            self._expect(_TOKEN_RPAREN)
            return expr
        raise ParseError(
            f"Expected variable or '(', got " f"'{self.tokens[self.pos][1]}'"
        )


def parse(formula_str: str) -> Formula:
    """Parse a propositional formula string into an AST.

    Supported syntax:
        - Variables: p, q, r, myVar (alphanumeric, starting with letter)
        - Negation: ~p or -p
        - Conjunction: p & q
        - Disjunction: p | q
        - Implication: p -> q
        - Bi-implication: p <-> q
        - Parentheses: (p | q) & r

    Precedence (high to low): ~, &, |, ->, <->

    Args:
        formula_str: The formula string to parse.

    Returns:
        The parsed Formula AST.

    Raises:
        ParseError: If the formula string is syntactically invalid.
    """
    tokens = _tokenize(formula_str)
    parser = _Parser(tokens)
    return parser.parse()


# ---------------------------------------------------------------------------
# Negation Normal Form (NNF)
# ---------------------------------------------------------------------------


def to_nnf(f: Formula) -> Formula:
    """Convert a formula to Negation Normal Form.

    In NNF, negations only appear directly before atomic variables.
    Uses De Morgan's laws and double negation elimination.

    Args:
        f: The input formula.

    Returns:
        An equivalent formula in NNF.
    """
    if isinstance(f, Var):
        return f

    if isinstance(f, Not):
        inner = f.inner
        # Double negation: ~~A → A
        if isinstance(inner, Not):
            return to_nnf(inner.inner)
        # De Morgan: ~(A & B) → ~A | ~B
        if isinstance(inner, And):
            return Or(to_nnf(Not(inner.left)), to_nnf(Not(inner.right)))
        # De Morgan: ~(A | B) → ~A & ~B
        if isinstance(inner, Or):
            return And(to_nnf(Not(inner.left)), to_nnf(Not(inner.right)))
        # ~Var is already NNF
        if isinstance(inner, Var):
            return f
        return to_nnf(Not(to_nnf(inner)))  # Ensure inner is simplified first

    if isinstance(f, And):
        return And(to_nnf(f.left), to_nnf(f.right))

    if isinstance(f, Or):
        return Or(to_nnf(f.left), to_nnf(f.right))

    return f  # pragma: no cover


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------


def complexity(f: Formula) -> int:
    """Count the number of nodes (connectives + atoms) in a formula.

    Args:
        f: The input formula.

    Returns:
        Total node count.
    """
    if isinstance(f, Var):
        return 1
    if isinstance(f, Not):
        return 1 + complexity(f.inner)
    if isinstance(f, (And, Or)):
        return 1 + complexity(f.left) + complexity(f.right)
    return 0  # pragma: no cover


def atoms(f: Formula) -> FrozenSet[str]:
    """Extract all atomic variable names from a formula.

    Args:
        f: The input formula.

    Returns:
        Frozenset of variable name strings.
    """
    if isinstance(f, Var):
        return frozenset({f.name})
    if isinstance(f, Not):
        return atoms(f.inner)
    if isinstance(f, (And, Or)):
        return atoms(f.left) | atoms(f.right)
    return frozenset()  # pragma: no cover


def is_literal(f: Formula) -> bool:
    """Check whether a formula is an atomic literal.

    A literal is either a variable (p) or its negation (~p).

    Args:
        f: The input formula.

    Returns:
        True if f is a literal.
    """
    if isinstance(f, Var):
        return True
    if isinstance(f, Not) and isinstance(f.inner, Var):
        return True
    return False


def negate(f: Formula) -> Formula:
    """Produce the negation of a formula (not NNF-simplified).

    Args:
        f: The formula to negate.

    Returns:
        Not(f), or f.inner if f is already a Not.
    """
    if isinstance(f, Not):
        return f.inner
    return Not(f)


def are_complementary(a: Formula, b: Formula) -> bool:
    """Check whether two literals are complementary (p and ~p).

    Args:
        a: First literal.
        b: Second literal.

    Returns:
        True if one is the negation of the other.
    """
    if isinstance(a, Var) and isinstance(b, Not):
        return isinstance(b.inner, Var) and a.name == b.inner.name
    if isinstance(b, Var) and isinstance(a, Not):
        return isinstance(a.inner, Var) and b.name == a.inner.name
    return False
