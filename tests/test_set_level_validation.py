"""Set-level validation: defects only visible across formulas.

check_well_formed validated each formula in isolation, so a set the prover
would refuse could be reported valid. The motivating case, verbatim from a real
run:

    exists x (biosynthetic_precursor(x))
    exists x (biosynthetic_precursor(glutamate, glutamine))

Each is well-formed alone; together they are not, because Prover9 requires one
fixed arity per symbol. The agent asked the validator, was told the formulas
were fine, and resubmitted the same set three times before giving up.
"""

from mcp_logic.syntax_validator import validate_formulas


def test_inconsistent_arity_across_formulas_is_invalid():
    result = validate_formulas(
        [
            "exists x (biosynthetic_precursor(x))",
            "exists x (biosynthetic_precursor(glutamate, glutamine))",
        ]
    )
    assert result["valid"] is False
    assert len(result["set_errors"]) == 1
    assert "biosynthetic_precursor" in result["set_errors"][0]


def test_each_formula_still_reports_itself_as_valid():
    # The per-formula verdicts are not wrong and must not be overwritten — the
    # defect belongs to the SET. Callers reading formula_results should still
    # see accurate individual results.
    result = validate_formulas(
        [
            "exists x (biosynthetic_precursor(x))",
            "exists x (biosynthetic_precursor(glutamate, glutamine))",
        ]
    )
    assert all(r["valid"] for r in result["formula_results"])


def test_error_names_the_symbol_and_both_arities():
    # "Syntax error or invalid input" is what Prover9 gives back. The whole
    # point of this check is to say which symbol and which arities.
    result = validate_formulas(
        [
            "p(x)",
            "p(x, y)",
        ]
    )
    message = result["set_errors"][0]
    assert "'p'" in message
    assert "1, 2" in message


def test_consistent_arity_across_formulas_is_valid():
    result = validate_formulas(
        [
            "exists x (amino_acid(x))",
            "precursor_of(glutamate, glutamine)",
            "precursor_of(aspartate, asparagine)",
            "all x (amino_acid(x) -> -codon(x))",
        ]
    )
    assert result["valid"] is True
    assert result["set_errors"] == []


def test_quantifiers_are_not_treated_as_symbols():
    # "all x (p(x))" must not read as a symbol `all` applied to arguments,
    # which would make every quantified set look inconsistent.
    result = validate_formulas(
        [
            "all x (p(x) -> q(x))",
            "exists x (p(x))",
            "all x all y (r(x, y) -> -s(x))",
            "exists x exists y (r(x, y))",
        ]
    )
    assert result["valid"] is True
    assert result["set_errors"] == []


def test_nested_application_counts_top_level_arguments_only():
    # f(g(x, y), z) is f/2 and g/2. Counting every comma would report f/3 and
    # invent a clash against a correct f(a, b) elsewhere in the set.
    result = validate_formulas(["f(g(x, y), z)", "f(a, b)", "g(c, d)"])
    assert result["valid"] is True
    assert result["set_errors"] == []


def test_reports_every_clashing_symbol():
    result = validate_formulas(["p(x)", "p(x, y)", "q(a)", "q(a, b, c)"])
    assert len(result["set_errors"]) == 2
    joined = " ".join(result["set_errors"])
    assert "'p'" in joined and "'q'" in joined


def test_single_formula_set_is_unaffected():
    result = validate_formulas(["all x (p(x) -> q(x))"])
    assert result["valid"] is True
    assert result["set_errors"] == []


def test_empty_input_is_valid():
    result = validate_formulas([])
    assert result["valid"] is True
    assert result["set_errors"] == []


def test_bare_atom_and_applied_predicate_have_inconsistent_arity():
    result = validate_formulas(["p", "p(a)"])
    assert result["valid"] is False
    assert len(result["set_errors"]) == 1
    assert "'p'" in result["set_errors"][0]
    assert "0, 1" in result["set_errors"][0]


def test_constant_and_applied_function_have_inconsistent_arity():
    result = validate_formulas(["q(f)", "q(f(a))"])
    assert result["valid"] is False
    assert len(result["set_errors"]) == 1
    assert "'f'" in result["set_errors"][0]
    assert "0, 1" in result["set_errors"][0]


def test_bound_variable_is_not_an_applied_symbol():
    result = validate_formulas(["all x (p(x))", "x(a, b)"])
    assert result["valid"] is True
    assert result["set_errors"] == []


def test_commas_inside_list_terms_do_not_inflate_arity():
    result = validate_formulas(["p([a, b], x)", "p(c, y)"])
    assert result["valid"] is True
    assert result["set_errors"] == []


def test_unparenthesized_quantifier_body_keeps_its_predicate_symbol():
    result = validate_formulas(["all x p(x)", "p(a, b)"])
    assert result["valid"] is False
    assert len(result["set_errors"]) == 1
    assert "'p'" in result["set_errors"][0]
    assert "1, 2" in result["set_errors"][0]
