"""Z3-backed arithmetic reasoning.

Prover9 is a pure first-order prover with **no theory of arithmetic**: it
has no idea that ``2 + 2 = 4``, that ``<`` is a total order, or that adding
one makes a number bigger.  Ask it anything numeric and it either grinds
until timeout or rejects the syntax outright.  That gap is why questions
like "every element has a successor" fell over on ``(x + 1) mod 3``.

Z3 closes it.  This module is a thin wrapper that keeps the same result
shape as :mod:`mcp_logic.server` and :mod:`mcp_logic.mace4_wrapper` so the
advisor's verified/unverified plumbing works unchanged.

Entailment is checked the standard way — assert the premises together with
the *negation* of the conclusion:

* ``unsat``   → the conclusion must hold. Proved.
* ``sat``     → there is a counterexample, returned as concrete values.
* ``unknown`` → Z3 gave up (nonlinear arithmetic, quantifiers).  Reported
  honestly rather than dressed up as either verdict.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("mcp_logic.smt_solver")

# Declarations are prepended to every script so callers can write plain
# constraints without repeating boilerplate.
_SUPPORTED_SORTS = {"Int", "Real", "Bool"}


class Z3NotInstalledError(RuntimeError):
    """Raised when the SMT tools are used without ``z3-solver`` present."""


def z3_available() -> bool:
    """Whether the optional ``z3-solver`` dependency can be imported."""
    try:
        import z3  # noqa: F401
    except ImportError:
        return False
    return True


def _require_z3() -> Any:
    try:
        import z3
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise Z3NotInstalledError(
            "z3-solver is not installed. Install it with: " "uv pip install z3-solver"
        ) from exc
    return z3


def build_declarations(
    variables: dict[str, str],
    functions: dict[str, list[str]] | None = None,
) -> str:
    """Render declarations for constants and uninterpreted functions.

    Args:
        variables: Mapping of variable name to sort (``Int``/``Real``/``Bool``).
        functions: Mapping of function name to ``[arg_sort, ..., result_sort]``.
            ``{"succ": ["Int", "Int"]}`` declares ``succ : Int -> Int``.

    Returns:
        SMT-LIB declaration lines.

    Raises:
        ValueError: If a sort is not one Z3 recognises here, or a function
            signature is too short to have a result sort.
    """
    lines: list[str] = []

    for name, sort in variables.items():
        if sort not in _SUPPORTED_SORTS:
            raise ValueError(
                f"Unsupported sort {sort!r} for {name!r}. "
                f"Use one of: {', '.join(sorted(_SUPPORTED_SORTS))}"
            )
        lines.append(f"(declare-const {name} {sort})")

    for name, signature in (functions or {}).items():
        if len(signature) < 1:
            raise ValueError(
                f"Function {name!r} needs at least a result sort, e.g. "
                f'{{"{name}": ["Int", "Int"]}} for Int -> Int'
            )
        for sort in signature:
            if sort not in _SUPPORTED_SORTS:
                raise ValueError(
                    f"Unsupported sort {sort!r} in signature for {name!r}."
                )
        *args, result = signature
        lines.append(f"(declare-fun {name} ({' '.join(args)}) {result})")

    return "\n".join(lines)


def _model_to_dict(model: Any) -> dict[str, str]:
    """Flatten a Z3 model into ``{name: value}`` strings."""
    return {str(decl.name()): str(model[decl]) for decl in model.decls()}


def check_entailment(
    premises: list[str],
    conclusion: str,
    variables: dict[str, str] | None = None,
    functions: dict[str, list[str]] | None = None,
    timeout_ms: int = 10_000,
) -> dict[str, Any]:
    """Does ``conclusion`` follow from ``premises`` over arithmetic?

    Args:
        premises: SMT-LIB assertions, e.g. ``["(> x 0)", "(= y (+ x 1))"]``.
        conclusion: A single SMT-LIB assertion to test.
        variables: Variable declarations, e.g. ``{"x": "Int"}``.
        functions: Uninterpreted function declarations, e.g.
            ``{"succ": ["Int", "Int"]}``.
        timeout_ms: Solver timeout in milliseconds.

    Returns:
        Result dict with ``result`` one of ``proved``, ``counterexample``,
        ``unknown`` or ``error``.
    """
    z3 = _require_z3()

    try:
        decls = build_declarations(variables or {}, functions)
    except ValueError as exc:
        return {"result": "error", "reason": str(exc)}

    # Assert the premises and the negated conclusion together.
    script = "\n".join(
        [
            decls,
            *[f"(assert {p})" for p in premises],
            f"(assert (not {conclusion}))",
        ]
    )

    solver = z3.Solver()
    solver.set("timeout", timeout_ms)

    try:
        solver.add(z3.parse_smt2_string(script))
    except z3.Z3Exception as exc:
        return {
            "result": "error",
            "reason": "SMT-LIB syntax error",
            "error": str(exc),
            "hint": (
                "Constraints use prefix notation: (> x 0), (= y (+ x 1)). "
                "Every variable must appear in `variables`."
            ),
            "script": script,
        }

    verdict = solver.check()

    if verdict == z3.unsat:
        return {
            "result": "proved",
            "reason": (
                "The negated conclusion is unsatisfiable, so the conclusion "
                "follows from the premises."
            ),
        }

    if verdict == z3.sat:
        return {
            "result": "counterexample",
            "reason": (
                "Found an assignment where every premise holds but the "
                "conclusion fails."
            ),
            "counterexample": _model_to_dict(solver.model()),
        }

    return {
        "result": "unknown",
        "reason": (
            f"Z3 could not decide within {timeout_ms} ms "
            f"({solver.reason_unknown()}). This is common for nonlinear "
            f"arithmetic and quantified formulas."
        ),
    }


def check_satisfiable(
    constraints: list[str],
    variables: dict[str, str] | None = None,
    functions: dict[str, list[str]] | None = None,
    timeout_ms: int = 10_000,
) -> dict[str, Any]:
    """Is there any assignment satisfying every constraint?

    Args:
        constraints: SMT-LIB assertions.
        variables: Variable declarations.
        functions: Uninterpreted function declarations.
        timeout_ms: Solver timeout in milliseconds.

    Returns:
        Result dict with ``result`` one of ``satisfiable``, ``unsatisfiable``,
        ``unknown`` or ``error``; a satisfying assignment is included as
        ``model`` when one exists.
    """
    z3 = _require_z3()

    try:
        decls = build_declarations(variables or {}, functions)
    except ValueError as exc:
        return {"result": "error", "reason": str(exc)}

    script = "\n".join([decls, *[f"(assert {c})" for c in constraints]])

    solver = z3.Solver()
    solver.set("timeout", timeout_ms)

    try:
        solver.add(z3.parse_smt2_string(script))
    except z3.Z3Exception as exc:
        return {
            "result": "error",
            "reason": "SMT-LIB syntax error",
            "error": str(exc),
            "script": script,
        }

    verdict = solver.check()

    if verdict == z3.sat:
        return {
            "result": "satisfiable",
            "model": _model_to_dict(solver.model()),
        }
    if verdict == z3.unsat:
        return {
            "result": "unsatisfiable",
            "reason": "The constraints contradict each other.",
        }
    return {
        "result": "unknown",
        "reason": f"Z3 could not decide ({solver.reason_unknown()}).",
    }
