"""Immutable first-order formulas and structural transformations.

This module models the Prover9 syntax accepted by :mod:`mcp_logic`.  It is
deliberately separate from :mod:`mcp_logic.formula_ast`, whose ``Var`` nodes
are propositional atoms rather than first-order terms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Var:
    """A first-order variable term."""

    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class Fn:
    """A function application; an empty argument tuple is a constant."""

    name: str
    args: tuple[Term, ...] = ()

    def __str__(self) -> str:
        if not self.args:
            return self.name
        return f"{self.name}({', '.join(map(str, self.args))})"


Term = Var | Fn


@dataclass(frozen=True, slots=True)
class Atom:
    """A predicate application; an empty argument tuple is allowed."""

    predicate: str
    args: tuple[Term, ...] = ()

    def __str__(self) -> str:
        if not self.args:
            return self.predicate
        return f"{self.predicate}({', '.join(map(str, self.args))})"


@dataclass(frozen=True, slots=True)
class Equal:
    left: Term
    right: Term

    def __str__(self) -> str:
        return f"{self.left} = {self.right}"


@dataclass(frozen=True, slots=True)
class Not:
    inner: Formula

    def __str__(self) -> str:
        if isinstance(self.inner, Atom):
            return f"-{self.inner}"
        return f"-({self.inner})"


@dataclass(frozen=True, slots=True)
class And:
    left: Formula
    right: Formula

    def __str__(self) -> str:
        return f"({self.left} & {self.right})"


@dataclass(frozen=True, slots=True)
class Or:
    left: Formula
    right: Formula

    def __str__(self) -> str:
        return f"({self.left} | {self.right})"


@dataclass(frozen=True, slots=True)
class Implies:
    left: Formula
    right: Formula

    def __str__(self) -> str:
        return f"({self.left} -> {self.right})"


@dataclass(frozen=True, slots=True)
class Iff:
    left: Formula
    right: Formula

    def __str__(self) -> str:
        return f"({self.left} <-> {self.right})"


@dataclass(frozen=True, slots=True)
class Forall:
    variable: str
    body: Formula

    def __str__(self) -> str:
        return f"all {self.variable} ({self.body})"


@dataclass(frozen=True, slots=True)
class Exists:
    variable: str
    body: Formula

    def __str__(self) -> str:
        return f"exists {self.variable} ({self.body})"


Formula = Atom | Equal | Not | And | Or | Implies | Iff | Forall | Exists


class ParseError(ValueError):
    """A syntax error with the zero-based position of the bad token."""

    def __init__(self, message: str, position: int) -> None:
        self.position = position
        super().__init__(f"{message} at position {position}")


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    value: str
    position: int


_TOKEN_RE = re.compile(
    r"(?P<SPACE>\s+)"
    r"|(?P<IFF><->)"
    r"|(?P<IMPLIES>->)"
    r"|(?P<NEQ>!=)"
    r"|(?P<NOT>[-~])"
    r"|(?P<AND>&)"
    r"|(?P<OR>\|)"
    r"|(?P<EQUAL>=)"
    r"|(?P<LPAREN>\()"
    r"|(?P<RPAREN>\))"
    r"|(?P<COMMA>,)"
    r"|(?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)"
)

# A binder always determines that its occurrences are variables.  For an
# otherwise free term, Prover9 text has no type marker that distinguishes a
# variable from a constant, so follow the project's public syntax contract:
# variable names use x/y/z (including historical generated names like xy2).
_FREE_VARIABLE_NAME = re.compile(r"[xyz]+[0-9]*\Z")


def _tokenize(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    position = 0
    while position < len(source):
        match = _TOKEN_RE.match(source, position)
        if match is None:
            raise ParseError(f"Unexpected character {source[position]!r}", position)
        kind = match.lastgroup
        if kind != "SPACE":
            if kind is None:  # Defensive: every tokenizer branch is named.
                raise ParseError("Tokenizer produced an unnamed token", position)
            value = match.group()
            if kind == "IDENT" and value in {"all", "exists"}:
                kind = value.upper()
            tokens.append(_Token(kind, value, position))
        position = match.end()
    tokens.append(_Token("EOF", "", len(source)))
    return tokens


class _Parser:
    def __init__(self, source: str) -> None:
        self.tokens = _tokenize(source)
        self.index = 0
        self.bound_variables: list[str] = []

    @property
    def current(self) -> _Token:
        return self.tokens[self.index]

    def accept(self, kind: str) -> _Token | None:
        if self.current.kind != kind:
            return None
        token = self.current
        self.index += 1
        return token

    def expect(self, kind: str) -> _Token:
        token = self.accept(kind)
        if token is None:
            raise ParseError(
                f"Expected {kind}, got {self.current.value!r}",
                self.current.position,
            )
        return token

    def parse(self) -> Formula:
        result = self.parse_iff()
        if self.current.kind != "EOF":
            raise ParseError(
                f"Unexpected token {self.current.value!r}", self.current.position
            )
        return result

    def parse_iff(self) -> Formula:
        left = self.parse_implies()
        if self.accept("IFF"):
            return Iff(left, self.parse_iff())
        return left

    def parse_implies(self) -> Formula:
        left = self.parse_or()
        if self.accept("IMPLIES"):
            return Implies(left, self.parse_implies())
        return left

    def parse_or(self) -> Formula:
        left = self.parse_and()
        while self.accept("OR"):
            left = Or(left, self.parse_and())
        return left

    def parse_and(self) -> Formula:
        left = self.parse_unary()
        while self.accept("AND"):
            left = And(left, self.parse_unary())
        return left

    def parse_unary(self) -> Formula:
        if self.accept("NOT"):
            return Not(self.parse_unary())
        if self.current.kind in {"ALL", "EXISTS"}:
            kind = self.current.kind
            self.index += 1
            variable = self.expect("IDENT").value
            self.bound_variables.append(variable)
            try:
                body = self.parse_unary()
            finally:
                self.bound_variables.pop()
            node = Forall if kind == "ALL" else Exists
            return node(variable, body)
        if self.accept("LPAREN"):
            body = self.parse_iff()
            self.expect("RPAREN")
            return body
        return self.parse_atomic()

    def parse_atomic(self) -> Formula:
        name = self.expect("IDENT").value
        args = self.parse_arguments()
        if self.current.kind in {"EQUAL", "NEQ"}:
            operator = self.current.kind
            self.index += 1
            left = self.term_from_name(name, args)
            right = self.parse_term()
            equality: Formula = Equal(left, right)
            return Not(equality) if operator == "NEQ" else equality
        return Atom(name, args)

    def parse_arguments(self) -> tuple[Term, ...]:
        if not self.accept("LPAREN"):
            return ()
        if self.current.kind == "RPAREN":
            raise ParseError("Empty argument list", self.current.position)
        args = [self.parse_term()]
        while self.accept("COMMA"):
            args.append(self.parse_term())
        self.expect("RPAREN")
        return tuple(args)

    def parse_term(self) -> Term:
        name = self.expect("IDENT").value
        return self.term_from_name(name, self.parse_arguments())

    def term_from_name(self, name: str, args: tuple[Term, ...]) -> Term:
        if args:
            return Fn(name, args)
        if name in self.bound_variables or _FREE_VARIABLE_NAME.fullmatch(name):
            return Var(name)
        return Fn(name)


def parse(source: str) -> Formula:
    """Parse one Prover9-style first-order formula."""

    return _Parser(source).parse()


def _term_variables(term: Term) -> set[str]:
    if isinstance(term, Var):
        return {term.name}
    variables: set[str] = set()
    for argument in term.args:
        variables.update(_term_variables(argument))
    return variables


def free_variables(formula: Formula) -> set[str]:
    """Return the variables that occur outside any matching quantifier."""

    def visit(node: Formula, bound: frozenset[str]) -> set[str]:
        if isinstance(node, Atom):
            present: set[str] = set()
            for argument in node.args:
                present.update(_term_variables(argument))
            return present - bound
        if isinstance(node, Equal):
            return (_term_variables(node.left) | _term_variables(node.right)) - bound
        if isinstance(node, Not):
            return visit(node.inner, bound)
        if isinstance(node, (And, Or, Implies, Iff)):
            return visit(node.left, bound) | visit(node.right, bound)
        if isinstance(node, (Forall, Exists)):
            return visit(node.body, bound | {node.variable})
        raise TypeError(f"Unsupported formula node: {type(node).__name__}")

    return visit(formula, frozenset())


def bound_variables(formula: Formula) -> set[str]:
    """Return every variable name introduced by a quantifier."""

    if isinstance(formula, (Atom, Equal)):
        return set()
    if isinstance(formula, Not):
        return bound_variables(formula.inner)
    if isinstance(formula, (And, Or, Implies, Iff)):
        return bound_variables(formula.left) | bound_variables(formula.right)
    if isinstance(formula, (Forall, Exists)):
        return {formula.variable} | bound_variables(formula.body)
    raise TypeError(f"Unsupported formula node: {type(formula).__name__}")


def unused_bound_variables(formula: Formula) -> set[str]:
    """Return binders whose variable has no occurrence in its own scope."""

    if isinstance(formula, (Atom, Equal)):
        return set()
    if isinstance(formula, Not):
        return unused_bound_variables(formula.inner)
    if isinstance(formula, (And, Or, Implies, Iff)):
        return unused_bound_variables(formula.left) | unused_bound_variables(
            formula.right
        )
    if isinstance(formula, (Forall, Exists)):
        unused = unused_bound_variables(formula.body)
        if formula.variable not in free_variables(formula.body):
            unused.add(formula.variable)
        return unused
    raise TypeError(f"Unsupported formula node: {type(formula).__name__}")


def _record_symbol(symbols: dict[str, int], name: str, arity: int) -> None:
    previous = symbols.get(name)
    if previous is not None and previous != arity:
        raise ValueError(
            f"Symbol {name!r} has inconsistent arities {previous} and {arity}"
        )
    symbols[name] = arity


def _collect_term_symbols(term: Term, symbols: dict[str, int]) -> None:
    if isinstance(term, Var):
        return
    _record_symbol(symbols, term.name, len(term.args))
    for argument in term.args:
        _collect_term_symbols(argument, symbols)


def function_symbols(formula: Formula) -> dict[str, int]:
    """Return function and constant symbols mapped to their arities."""

    symbols: dict[str, int] = {}

    def visit(node: Formula) -> None:
        if isinstance(node, Atom):
            for argument in node.args:
                _collect_term_symbols(argument, symbols)
        elif isinstance(node, Equal):
            _collect_term_symbols(node.left, symbols)
            _collect_term_symbols(node.right, symbols)
        elif isinstance(node, Not):
            visit(node.inner)
        elif isinstance(node, (And, Or, Implies, Iff)):
            visit(node.left)
            visit(node.right)
        elif isinstance(node, (Forall, Exists)):
            visit(node.body)
        else:
            raise TypeError(f"Unsupported formula node: {type(node).__name__}")

    visit(formula)
    return symbols


def predicate_symbols(formula: Formula) -> dict[str, int]:
    """Return predicate symbols mapped to their arities."""

    symbols: dict[str, int] = {}

    def visit(node: Formula) -> None:
        if isinstance(node, Atom):
            _record_symbol(symbols, node.predicate, len(node.args))
        elif isinstance(node, Equal):
            return
        elif isinstance(node, Not):
            visit(node.inner)
        elif isinstance(node, (And, Or, Implies, Iff)):
            visit(node.left)
            visit(node.right)
        elif isinstance(node, (Forall, Exists)):
            visit(node.body)
        else:
            raise TypeError(f"Unsupported formula node: {type(node).__name__}")

    visit(formula)
    return symbols


def _without_implications(formula: Formula) -> Formula:
    if isinstance(formula, (Atom, Equal)):
        return formula
    if isinstance(formula, Not):
        return Not(_without_implications(formula.inner))
    if isinstance(formula, And):
        return And(
            _without_implications(formula.left),
            _without_implications(formula.right),
        )
    if isinstance(formula, Or):
        return Or(
            _without_implications(formula.left),
            _without_implications(formula.right),
        )
    if isinstance(formula, Implies):
        return Or(
            Not(_without_implications(formula.left)),
            _without_implications(formula.right),
        )
    if isinstance(formula, Iff):
        left = _without_implications(formula.left)
        right = _without_implications(formula.right)
        return And(Or(Not(left), right), Or(Not(right), left))
    if isinstance(formula, Forall):
        return Forall(formula.variable, _without_implications(formula.body))
    if isinstance(formula, Exists):
        return Exists(formula.variable, _without_implications(formula.body))
    raise TypeError(f"Unsupported formula node: {type(formula).__name__}")


def _to_nnf(formula: Formula, negated: bool = False) -> Formula:
    if isinstance(formula, (Atom, Equal)):
        return Not(formula) if negated else formula
    if isinstance(formula, Not):
        return _to_nnf(formula.inner, not negated)
    if isinstance(formula, And):
        connective = Or if negated else And
        return connective(
            _to_nnf(formula.left, negated),
            _to_nnf(formula.right, negated),
        )
    if isinstance(formula, Or):
        connective = And if negated else Or
        return connective(
            _to_nnf(formula.left, negated),
            _to_nnf(formula.right, negated),
        )
    if isinstance(formula, Forall):
        quantifier = Exists if negated else Forall
        return quantifier(formula.variable, _to_nnf(formula.body, negated))
    if isinstance(formula, Exists):
        quantifier = Forall if negated else Exists
        return quantifier(formula.variable, _to_nnf(formula.body, negated))
    raise TypeError("Implications must be eliminated before NNF conversion")


def _fresh_variable(base: str, used: set[str]) -> str:
    suffix = 1
    while f"{base}_{suffix}" in used:
        suffix += 1
    return f"{base}_{suffix}"


def _standardize_apart(formula: Formula) -> Formula:
    used = set(free_variables(formula))

    def rename_term(term: Term, environment: dict[str, str]) -> Term:
        if isinstance(term, Var):
            return Var(environment.get(term.name, term.name))
        return Fn(
            term.name,
            tuple(rename_term(argument, environment) for argument in term.args),
        )

    def visit(node: Formula, environment: dict[str, str]) -> Formula:
        if isinstance(node, Atom):
            return Atom(
                node.predicate,
                tuple(rename_term(argument, environment) for argument in node.args),
            )
        if isinstance(node, Equal):
            return Equal(
                rename_term(node.left, environment),
                rename_term(node.right, environment),
            )
        if isinstance(node, Not):
            return Not(visit(node.inner, environment))
        if isinstance(node, (And, Or)):
            return type(node)(
                visit(node.left, environment), visit(node.right, environment)
            )
        if isinstance(node, (Forall, Exists)):
            variable = node.variable
            if variable in used:
                variable = _fresh_variable(variable, used)
            used.add(variable)
            nested_environment = dict(environment)
            nested_environment[node.variable] = variable
            return type(node)(variable, visit(node.body, nested_environment))
        raise TypeError(f"Unexpected formula in NNF: {type(node).__name__}")

    return visit(formula, {})


def _pull_quantifiers(
    formula: Formula,
) -> tuple[list[tuple[type[Forall] | type[Exists], str]], Formula]:
    if isinstance(formula, (Atom, Equal, Not)):
        return [], formula
    if isinstance(formula, (And, Or)):
        left_prefix, left = _pull_quantifiers(formula.left)
        right_prefix, right = _pull_quantifiers(formula.right)
        return [*left_prefix, *right_prefix], type(formula)(left, right)
    if isinstance(formula, (Forall, Exists)):
        prefix, matrix = _pull_quantifiers(formula.body)
        return [(type(formula), formula.variable), *prefix], matrix
    raise TypeError(f"Unexpected formula in NNF: {type(formula).__name__}")


def prenex(formula: Formula) -> Formula:
    """Return an equivalent capture-avoiding prenex-normal formula.

    Implications are removed and negations are pushed to atoms before bound
    variables are standardized apart.  That standardization is what makes it
    safe to pull every quantifier over the quantifier-free matrix.
    """

    nnf = _to_nnf(_without_implications(formula))
    standardized = _standardize_apart(nnf)
    prefix, matrix = _pull_quantifiers(standardized)
    result = matrix
    for quantifier, variable in reversed(prefix):
        result = quantifier(variable, result)
    return result


def _substitute_term(term: Term, variable: str, replacement: Term) -> Term:
    if isinstance(term, Var):
        return replacement if term.name == variable else term
    return Fn(
        term.name,
        tuple(
            _substitute_term(argument, variable, replacement) for argument in term.args
        ),
    )


def _substitute(formula: Formula, variable: str, replacement: Term) -> Formula:
    if isinstance(formula, Atom):
        return Atom(
            formula.predicate,
            tuple(
                _substitute_term(argument, variable, replacement)
                for argument in formula.args
            ),
        )
    if isinstance(formula, Equal):
        return Equal(
            _substitute_term(formula.left, variable, replacement),
            _substitute_term(formula.right, variable, replacement),
        )
    if isinstance(formula, Not):
        return Not(_substitute(formula.inner, variable, replacement))
    if isinstance(formula, (And, Or, Implies, Iff)):
        return type(formula)(
            _substitute(formula.left, variable, replacement),
            _substitute(formula.right, variable, replacement),
        )
    if isinstance(formula, (Forall, Exists)):
        if formula.variable == variable:
            return formula
        return type(formula)(
            formula.variable,
            _substitute(formula.body, variable, replacement),
        )
    raise TypeError(f"Unsupported formula node: {type(formula).__name__}")


def skolemize(formula: Formula) -> Formula:
    """Eliminate existential quantifiers with fresh Skolem functions.

    The result remains universally quantified.  Free variables are treated as
    implicitly universal, matching Prover9's interpretation, so an existential
    inside an open formula receives those variables as arguments too.
    """

    normalized = prenex(formula)
    used_names = (
        set(function_symbols(normalized))
        | set(predicate_symbols(normalized))
        | free_variables(normalized)
        | bound_variables(normalized)
    )

    def fresh_skolem_name() -> str:
        suffix = 0
        while True:
            candidate = "skolem" if suffix == 0 else f"skolem_{suffix}"
            if candidate not in used_names:
                used_names.add(candidate)
                return candidate
            suffix += 1

    def visit(node: Formula, universals: tuple[str, ...]) -> Formula:
        if isinstance(node, Forall):
            return Forall(
                node.variable,
                visit(node.body, (*universals, node.variable)),
            )
        if isinstance(node, Exists):
            replacement = Fn(
                fresh_skolem_name(), tuple(Var(name) for name in universals)
            )
            return visit(_substitute(node.body, node.variable, replacement), universals)
        return node

    implicit_universals = tuple(sorted(free_variables(normalized)))
    return visit(normalized, implicit_universals)
