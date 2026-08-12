"""Behavioral contract for the first-order formula AST."""

import pytest

from mcp_logic.categorical_helpers import (
    CategoricalHelpers,
    group_axioms,
    monoid_axioms,
)
from mcp_logic.fol_ast import (
    And,
    Atom,
    Exists,
    Fn,
    Forall,
    Implies,
    Not,
    Or,
    ParseError,
    Var,
    bound_variables,
    free_variables,
    function_symbols,
    parse,
    predicate_symbols,
    prenex,
    skolemize,
)


def test_parses_canonical_quantified_implication_and_round_trips() -> None:
    formula = parse("all x (human(x) -> mortal(x))")

    assert formula == Forall(
        "x",
        Implies(
            Atom("human", (Var("x"),)),
            Atom("mortal", (Var("x"),)),
        ),
    )
    assert parse(str(formula)) == formula


ROUND_TRIP_FORMULAS = [
    *CategoricalHelpers.category_axioms(),
    *CategoricalHelpers.functor_axioms(),
    *monoid_axioms(),
    *group_axioms(),
    "human(socrates)",
    "-mortal(socrates)",
    "x = f(g(y), a)",
    "x != y",
    "p(x) | q(y) & r(z)",
    "p <-> (q -> r)",
    "exists x (pet(x) & dog(x))",
    "all x (p(x) -> exists y (parent(y, x)))",
]


@pytest.mark.parametrize("source", ROUND_TRIP_FORMULAS)
def test_existing_first_order_formulas_round_trip(source: str) -> None:
    formula = parse(source)

    assert parse(str(formula)) == formula


def test_parse_error_reports_the_offending_position() -> None:
    with pytest.raises(ParseError) as caught:
        parse("human(@)")

    assert caught.value.position == 6


def test_finds_free_result_variable_in_historical_associativity_shape() -> None:
    formula = parse(
        "all x all y "
        "(mult(x, y, xy2) -> exists z (mult(xy2, z, xyz2) & product(xyz2)))"
    )

    assert free_variables(formula) == {"xy2", "xyz2"}


def test_finds_exact_historical_xy2_hazard() -> None:
    formula = parse("all x all y (mult(x, y, xy2) -> product(xy2))")

    assert free_variables(formula) == {"xy2"}


def test_reports_bound_variables_and_symbol_arities_structurally() -> None:
    formula = parse("all x exists y (edge(f(x), y) & (weight(y) = zero | marked(x)))")

    assert bound_variables(formula) == {"x", "y"}
    assert function_symbols(formula) == {"f": 1, "weight": 1, "zero": 0}
    assert predicate_symbols(formula) == {"edge": 2, "marked": 1}


def test_prenex_standardizes_bound_variables_away_from_free_ones() -> None:
    source = parse("(exists x p(x)) & q(x)")

    result = prenex(source)

    assert result == Exists(
        "x_1",
        And(Atom("p", (Var("x_1"),)), Atom("q", (Var("x"),))),
    )
    assert free_variables(result) == {"x"}


def test_prenex_pushes_negation_through_implication_and_quantifiers() -> None:
    result = prenex(parse("-(all x (p(x) -> exists y q(x, y)))"))

    assert result == Exists(
        "x",
        Forall(
            "y",
            And(
                Atom("p", (Var("x"),)),
                Not(Atom("q", (Var("x"), Var("y")))),
            ),
        ),
    )


def test_prenex_standardizes_shadowed_variables_apart() -> None:
    result = prenex(parse("all x (p(x) | exists x q(x))"))

    assert result == Forall(
        "x",
        Exists(
            "x_1",
            Or(
                Atom("p", (Var("x"),)),
                Atom("q", (Var("x_1"),)),
            ),
        ),
    )


def test_skolemize_uses_preceding_universals_as_function_arguments() -> None:
    source = parse("exists x all y exists z relation(x, y, z)")

    result = skolemize(source)

    assert result == Forall(
        "y",
        Atom(
            "relation",
            (
                Fn("skolem"),
                Var("y"),
                Fn("skolem_1", (Var("y"),)),
            ),
        ),
    )
    assert function_symbols(result) == {"skolem": 0, "skolem_1": 1}


def test_skolemize_depends_on_implicitly_universal_free_variables() -> None:
    result = skolemize(parse("exists y relation(x, y)"))

    assert result == Atom(
        "relation",
        (Var("x"), Fn("skolem", (Var("x"),))),
    )
    assert free_variables(result) == {"x"}


def test_skolemize_avoids_existing_symbol_names() -> None:
    result = skolemize(parse("exists x relation(skolem, x)"))

    assert result == Atom(
        "relation",
        (Fn("skolem"), Fn("skolem_1")),
    )
