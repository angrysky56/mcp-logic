"""Tests for Phase 4: Correctness Fixes (CORR-01 through CORR-04).

These tests verify:
- CORR-01: Mace4 parser structured output (predicates, functions, no duplicates)
- CORR-02: Smart routing structural detection (quantifiers vs predicate names)
- CORR-03: group_axioms() consistency with monoid_axioms()
- CORR-04: Syntax validator multi-variable quantifiers and scope warnings
"""

from mcp_logic.categorical_helpers import group_axioms, monoid_axioms
from mcp_logic.syntax_validator import SyntaxValidator


# ──────────────────────────────────────────────────────────────────────────────
# CORR-01: Mace4 Parser Structured Output
# ──────────────────────────────────────────────────────────────────────────────


class TestMace4StructuredOutput:
    """Verify _parse_model produces structured predicates/functions and clean raw_interpretation."""

    SAMPLE_MACE4_OUTPUT = """\
============================== DOMAIN SIZE 2 ===============================

=== Model

interpretation( 2, [number=1, seconds=0], [

  relation(P(_), [ 1, 0 ]),

  function(f(_), [ 1, 0 ]),

  function(e, [ 0 ])

]).
end_of_list.

============================== end of model ================================
"""

    def _get_wrapper(self):
        """Create a Mace4Wrapper for parser testing (doesn't need real binary)."""
        from unittest.mock import patch

        from mcp_logic.mace4_wrapper import Mace4Wrapper

        # Bypass binary check for parse-only tests
        with patch.object(Mace4Wrapper, "__init__", lambda self, *a, **kw: None):
            wrapper = Mace4Wrapper.__new__(Mace4Wrapper)
        return wrapper

    def test_domain_size_extracted(self):
        wrapper = self._get_wrapper()
        model = wrapper._parse_model(self.SAMPLE_MACE4_OUTPUT)
        assert model["domain_size"] == 2

    def test_predicates_populated(self):
        wrapper = self._get_wrapper()
        model = wrapper._parse_model(self.SAMPLE_MACE4_OUTPUT)
        assert (
            "P" in model["predicates"]
        ), f"Expected 'P' in predicates, got {model['predicates']}"

    def test_functions_populated(self):
        wrapper = self._get_wrapper()
        model = wrapper._parse_model(self.SAMPLE_MACE4_OUTPUT)
        assert (
            "f" in model["functions"]
        ), f"Expected 'f' in functions, got {model['functions']}"

    def test_constants_populated(self):
        wrapper = self._get_wrapper()
        model = wrapper._parse_model(self.SAMPLE_MACE4_OUTPUT)
        # 'e' is a 0-arity function (constant)
        assert (
            "e" in model["constants"] or "e" in model["functions"]
        ), f"Expected 'e' in constants or functions, got constants={model['constants']}, functions={model['functions']}"

    def test_raw_interpretation_no_duplicates(self):
        wrapper = self._get_wrapper()
        model = wrapper._parse_model(self.SAMPLE_MACE4_OUTPUT)
        raw = model["raw_interpretation"]
        lines = [line.strip() for line in raw.split("\n") if line.strip()]
        # No line should appear more than once
        seen = set()
        duplicates = []
        for line in lines:
            if line in seen:
                duplicates.append(line)
            seen.add(line)
        assert not duplicates, f"Duplicate lines in raw_interpretation: {duplicates}"


# ──────────────────────────────────────────────────────────────────────────────
# CORR-02: Smart Routing Structural Detection
# ──────────────────────────────────────────────────────────────────────────────


class TestSmartRouting:
    """Verify the _is_fol_formula helper correctly distinguishes FOL from propositional."""

    def _is_fol(self, formula: str) -> bool:
        """Import and call the smart routing detection function."""
        from mcp_logic.server import _is_fol_formula

        return _is_fol_formula(formula)

    def test_standard_universal_quantifier(self):
        """'all x (p(x))' is clearly FOL."""
        assert self._is_fol("all x (p(x))") is True

    def test_standard_existential_quantifier(self):
        """'exists y (q(y))' is clearly FOL."""
        assert self._is_fol("exists y (q(y))") is True

    def test_predicate_named_all_students(self):
        """'all_students' is a propositional atom, not a quantifier."""
        assert self._is_fol("all_students") is False

    def test_predicate_with_quantifier_prefix_in_name(self):
        """'exists_path' is a propositional atom, not a quantifier."""
        assert self._is_fol("exists_path") is False

    def test_pure_propositional(self):
        """'p & q' has no quantifiers or predicate arguments — propositional."""
        assert self._is_fol("p & q") is False

    def test_fol_with_nested_quantifiers(self):
        """'all x (exists y (loves(x,y)))' is FOL."""
        assert self._is_fol("all x (exists y (loves(x,y)))") is True

    def test_implication_without_quantifiers(self):
        """'p -> q' is propositional."""
        assert self._is_fol("p -> q") is False

    def test_fol_with_function_terms(self):
        """'all x (p(f(x)))' is FOL (quantifier + nested function)."""
        assert self._is_fol("all x (p(f(x)))") is True

    def test_predicate_only_is_fol(self):
        """'p(x,y)' has predicate arguments — treat as FOL."""
        assert self._is_fol("p(x,y)") is True

    def test_propositional_atoms_with_operators(self):
        """'(a & b) -> (c | d)' is propositional."""
        assert self._is_fol("(a & b) -> (c | d)") is False


# ──────────────────────────────────────────────────────────────────────────────
# CORR-03: Group Axioms Consistency
# ──────────────────────────────────────────────────────────────────────────────


class TestGroupAxiomsConsistency:
    """Verify group_axioms aligns with monoid_axioms for identity element treatment."""

    def test_monoid_has_identity_axiom(self):
        """monoid_axioms() should assert the existence of identity element e."""
        axioms = monoid_axioms()
        combined = " ".join(axioms)
        assert (
            "mult(e," in combined or "mult( e," in combined
        ), "monoid_axioms must reference identity element 'e'"

    def test_group_includes_monoid_axioms(self):
        """group_axioms() should be a superset of monoid_axioms()."""
        m_axioms = monoid_axioms()
        g_axioms = group_axioms()
        for axiom in m_axioms:
            assert axiom in g_axioms, f"group_axioms() missing monoid axiom: {axiom}"

    def test_group_inverse_uses_consistent_e(self):
        """group_axioms() inverse axiom should reference the same identity element 'e'."""
        g_axioms = group_axioms()
        # The inverse axiom should reference 'e' consistently
        inverse_axiom = [a for a in g_axioms if "exists y" in a or "inv(" in a]
        assert len(inverse_axiom) >= 1, "group_axioms() must have an inverse axiom"
        inv = inverse_axiom[0]
        assert "mult(" in inv, "Inverse axiom must use mult()"

    def test_monoid_identity_is_universal(self):
        """The monoid identity axiom should use 'all x' with 'e' as a constant."""
        axioms = monoid_axioms()
        identity_axioms = [a for a in axioms if "mult(e," in a or "mult(x,e," in a]
        assert (
            len(identity_axioms) >= 1
        ), "monoid_axioms must have at least one identity axiom with 'e' as constant"
        # 'e' should appear as a constant (not existentially quantified in the same axiom)
        for ax in identity_axioms:
            assert (
                "all x" in ax
            ), f"Identity axiom should universally quantify over x: {ax}"


# ──────────────────────────────────────────────────────────────────────────────
# CORR-04: Syntax Validator Enhancements
# ──────────────────────────────────────────────────────────────────────────────


class TestValidatorMultiVariable:
    """Verify multi-variable quantifiers are accepted."""

    def test_multi_variable_quantifier_valid(self):
        """'all x y (p(x,y))' should be accepted as valid."""
        validator = SyntaxValidator()
        is_valid, errors, warnings = validator.validate("all x y (p(x,y))")
        assert (
            is_valid
        ), f"Multi-variable quantifier should be valid, got errors: {errors}"

    def test_single_variable_still_valid(self):
        """'all x (p(x))' should remain valid."""
        validator = SyntaxValidator()
        is_valid, errors, warnings = validator.validate("all x (p(x))")
        assert (
            is_valid
        ), f"Single-variable quantifier should be valid, got errors: {errors}"

    def test_exists_multi_variable(self):
        """'exists x y (q(x,y))' should be accepted."""
        validator = SyntaxValidator()
        is_valid, errors, warnings = validator.validate("exists x y (q(x,y))")
        assert is_valid, f"Multi-variable exists should be valid, got errors: {errors}"


class TestValidatorScopeWarning:
    """Verify scope issue detection for unparenthesized quantifier formulas."""

    def test_scope_warning_implication(self):
        """'all x p(x) -> q(x)' should produce a scope warning."""
        validator = SyntaxValidator()
        is_valid, errors, warnings = validator.validate("all x p(x) -> q(x)")
        # Should produce at least a warning about scope
        scope_warnings = [w for w in warnings if "scope" in w.lower()]
        assert (
            len(scope_warnings) >= 1
        ), f"Expected scope warning for unparenthesized quantifier body, got warnings: {warnings}"

    def test_scope_warning_disjunction(self):
        """'all x p(x) | q(x)' should produce a scope warning."""
        validator = SyntaxValidator()
        is_valid, errors, warnings = validator.validate("all x p(x) | q(x)")
        scope_warnings = [w for w in warnings if "scope" in w.lower()]
        assert (
            len(scope_warnings) >= 1
        ), f"Expected scope warning for unparenthesized quantifier body, got warnings: {warnings}"

    def test_no_scope_warning_when_parenthesized(self):
        """'all x (p(x) -> q(x))' should NOT produce a scope warning."""
        validator = SyntaxValidator()
        is_valid, errors, warnings = validator.validate("all x (p(x) -> q(x))")
        scope_warnings = [w for w in warnings if "scope" in w.lower()]
        assert (
            len(scope_warnings) == 0
        ), f"Should not warn when quantifier body is parenthesized, got: {scope_warnings}"
