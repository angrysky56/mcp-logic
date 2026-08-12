"""Conservative recognition of finite-model decidable FOL fragments."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mcp_logic.fol_ast import (
    And,
    Atom,
    Equal,
    Exists,
    Forall,
    Formula,
    Iff,
    Implies,
    Not,
    Or,
    ParseError,
    function_symbols,
    parse,
    predicate_symbols,
    prenex,
    skolemize,
)
from mcp_logic.syntax_validator import normalize_formula


@dataclass(frozen=True, slots=True)
class FragmentVerdict:
    """Whether a formula set has a licensed finite-model decision bound."""

    fragment: str
    decidable: bool
    model_bound: int | None
    reason: str


def _quantifier_prefix(formula: Formula) -> list[type[Forall] | type[Exists]]:
    prefix: list[type[Forall] | type[Exists]] = []
    node = prenex(formula)
    while isinstance(node, (Forall, Exists)):
        prefix.append(type(node))
        node = node.body
    return prefix


def _bsr_verdict(formulas: Sequence[Formula]) -> FragmentVerdict | None:
    constants: set[str] = set()
    existential_count = 0

    for formula in formulas:
        skolem_symbols = function_symbols(skolemize(formula))
        if any(arity >= 1 for arity in skolem_symbols.values()):
            return None

        constants.update(
            name for name, arity in function_symbols(formula).items() if arity == 0
        )
        existential_count += _quantifier_prefix(formula).count(Exists)

    model_bound = max(1, existential_count + len(constants))
    return FragmentVerdict(
        fragment="bsr",
        decidable=True,
        model_bound=model_bound,
        reason=(
            "The prenex theory is in the Bernays-Schönfinkel-Ramsey fragment: "
            "Skolemization introduces constants only, so a complete finite-model "
            f"search needs domains of size 1 through {model_bound}."
        ),
    )


def _contains_equality(formula: Formula) -> bool:
    if isinstance(formula, Equal):
        return True
    if isinstance(formula, Atom):
        return False
    if isinstance(formula, Not):
        return _contains_equality(formula.inner)
    if isinstance(formula, (And, Or, Implies, Iff)):
        return _contains_equality(formula.left) or _contains_equality(formula.right)
    if isinstance(formula, (Forall, Exists)):
        return _contains_equality(formula.body)
    raise TypeError(f"Unsupported formula node: {type(formula).__name__}")


def _quantifier_rank(formula: Formula) -> int:
    if isinstance(formula, (Atom, Equal)):
        return 0
    if isinstance(formula, Not):
        return _quantifier_rank(formula.inner)
    if isinstance(formula, (And, Or, Implies, Iff)):
        return max(_quantifier_rank(formula.left), _quantifier_rank(formula.right))
    if isinstance(formula, (Forall, Exists)):
        return 1 + _quantifier_rank(formula.body)
    raise TypeError(f"Unsupported formula node: {type(formula).__name__}")


def _monadic_verdict(
    formulas: Sequence[Formula], model_cap: int
) -> FragmentVerdict | None:
    predicates: dict[str, int] = {}
    constants: set[str] = set()
    equality_present = False
    quantifier_rank = 0

    for formula in formulas:
        functions = function_symbols(formula)
        if any(arity >= 1 for arity in functions.values()):
            return None
        constants.update(name for name, arity in functions.items() if arity == 0)

        for name, arity in predicate_symbols(formula).items():
            if arity > 1:
                return None
            predicates[name] = arity

        equality_present = equality_present or _contains_equality(formula)
        quantifier_rank = max(quantifier_rank, _quantifier_rank(formula))

    unary_predicate_count = sum(arity == 1 for arity in predicates.values())
    unary_types = 2**unary_predicate_count
    if equality_present:
        # Equality can distinguish several elements having the same unary type.
        # A rank-q sentence cannot distinguish more than q unnamed elements of
        # one type; retain named constants separately as a conservative bound.
        model_bound = len(constants) + max(1, quantifier_rank) * unary_types
    else:
        # Without equality, elements of the same unary type can be collapsed.
        model_bound = unary_types
    model_bound = max(1, model_bound)

    if model_bound > model_cap:
        return FragmentVerdict(
            fragment="monadic",
            decidable=False,
            model_bound=None,
            reason=(
                "The theory is monadic, but its safe finite-model bound "
                f"({model_bound}) exceeds the configured cap ({model_cap})."
            ),
        )

    return FragmentVerdict(
        fragment="monadic",
        decidable=True,
        model_bound=model_bound,
        reason=(
            "Every predicate is at most unary and there are no positive-arity "
            f"function symbols; a complete search needs domains of size 1 "
            f"through {model_bound}."
        ),
    )


def classify_fragment(
    formulas: Sequence[str], *, monadic_model_cap: int = 1024
) -> FragmentVerdict:
    """Classify a conjunction of Prover9 formulas conservatively.

    Free variables follow Prover9 semantics and are treated as implicitly
    universal by the Skolemization-based BSR check.
    """

    try:
        parsed = [
            parse(normalize_formula(formula).rstrip(".").strip())
            for formula in formulas
        ]
    except (ParseError, ValueError) as exc:
        return FragmentVerdict(
            fragment="unknown",
            decidable=False,
            model_bound=None,
            reason=f"Fragment classification could not parse every formula: {exc}",
        )

    bsr = _bsr_verdict(parsed)
    if bsr is not None:
        return bsr
    monadic = _monadic_verdict(parsed, monadic_model_cap)
    if monadic is not None:
        return monadic
    return FragmentVerdict(
        fragment="unknown",
        decidable=False,
        model_bound=None,
        reason="The theory is outside the supported decidable fragments.",
    )


def classify_counterexample(
    premises: Sequence[str],
    conclusion: str,
    *,
    monadic_model_cap: int = 1024,
) -> FragmentVerdict:
    """Classify the actual countermodel theory: premises and negated goal."""

    normalized_conclusion = normalize_formula(conclusion).rstrip(".").strip()
    return classify_fragment(
        [*premises, f"-({normalized_conclusion})"],
        monadic_model_cap=monadic_model_cap,
    )
