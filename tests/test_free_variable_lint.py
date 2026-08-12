"""AST-based warnings for invisible implicit quantification hazards."""

from mcp_logic.categorical_helpers import group_axioms, monoid_axioms
from mcp_logic.syntax_validator import validate_formulas


def test_relational_associativity_warns_on_free_and_unused_variables() -> None:
    formula = (
        "all x all y all z all xy all yz all xyz1 all ybc "
        "(((mult(x,y,xy) & mult(y,z,yz)) & mult(xy,z,xyz1)) -> "
        "(mult(x,yz,xyz2) & xyz1 = xyz2))"
    )

    result = validate_formulas([formula])

    warnings = result["formula_results"][0]["warnings"]
    assert result["valid"] is True
    assert any(
        "`xyz2` is free and will be implicitly universally quantified" in warning
        for warning in warnings
    )
    assert any("`ybc` is bound but unused" in warning for warning in warnings)


def test_equational_monoid_and_group_axioms_have_no_variable_warnings() -> None:
    result = validate_formulas([*monoid_axioms(), *group_axioms()])

    warnings = [
        warning
        for formula_result in result["formula_results"]
        for warning in formula_result["warnings"]
        if "implicitly universally quantified" in warning
        or "bound but unused" in warning
    ]
    assert warnings == []
