"""
Syntax validator for logical formulas before sending to Prover9/Mace4.

Provides early feedback on common syntax errors to improve user experience.
"""

import re
from typing import List, Dict, Tuple


class SyntaxValidator:
    """Pre-validate logical formulas for common syntax errors"""

    # Common quantifiers and operators
    QUANTIFIERS = {"all", "exists"}
    OPERATORS = {"->", "<->", "&", "|", "-"}
    RESERVED = QUANTIFIERS | {"true", "false", "end_of_list"}

    def __init__(self):
        self.errors = []
        self.warnings = []

    def validate(self, formula: str) -> Tuple[bool, List[str], List[str]]:
        """Validate a logical formula

        Args:
            formula: Formula to validate

        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        self.errors = []
        self.warnings = []

        # Remove trailing period for analysis
        formula_clean = formula.rstrip(".")

        # Check balanced parentheses
        self._check_balanced_parens(formula_clean)

        # Check quantifier syntax
        self._check_quantifiers(formula_clean)

        # Check operator usage
        self._check_operators(formula_clean)

        # Check predicate/function naming
        self._check_naming(formula_clean)

        # Check for common mistakes
        self._check_common_mistakes(formula_clean)

        return (len(self.errors) == 0, self.errors, self.warnings)

    def _check_balanced_parens(self, formula: str):
        """Check if parentheses are balanced"""
        stack = []
        for i, char in enumerate(formula):
            if char == "(":
                stack.append(i)
            elif char == ")":
                if not stack:
                    self.errors.append(f"Unmatched closing parenthesis at position {i}")
                else:
                    stack.pop()

        if stack:
            self.errors.append(f"Unmatched opening parenthesis at position {stack[0]}")

    def _check_quantifiers(self, formula: str):
        """Check quantifier syntax"""
        # Pattern: quantifier variable (formula)
        # e.g., "all x" or "exists y"
        for quantifier in self.QUANTIFIERS:
            # Find all occurrences of this quantifier
            pattern = rf"\b{quantifier}\s+(\w+)"
            matches = re.finditer(pattern, formula)

            for match in matches:
                var = match.group(1)
                # Check if variable follows quantifier is lowercase
                if not var[0].islower():
                    self.warnings.append(f"Quantifier variable '{var}' should start with lowercase")

                # Check if there's a formula after the quantifier
                pos = match.end()
                remaining = formula[pos:].lstrip()
                if not remaining or remaining[0] != "(":
                    self.errors.append(f"Quantifier '{quantifier} {var}' must be followed by a formula in parentheses")

    def _check_operators(self, formula: str):
        """Check operator usage"""
        # Check for double operators (likely mistakes)
        for op in ["&", "|"]:
            if op + op in formula:
                self.warnings.append(f"Double operator '{op}{op}' found - did you mean to use it twice?")

        # Check for implication chains without parentheses
        if formula.count("->") > 1 and formula.count("(") == 0:
            self.warnings.append("Multiple implications without parentheses - consider adding parentheses for clarity")

    def _check_naming(self, formula: str):
        """Check predicate/function naming conventions"""
        # Extract potential predicate/function names
        # Pattern: word followed by opening paren
        pattern = r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\("
        matches = re.finditer(pattern, formula)

        for match in matches:
            name = match.group(1)

            # Skip quantifiers
            if name in self.QUANTIFIERS:
                continue

            # Predicates should start with lowercase
            if name[0].isupper():
                self.warnings.append(f"Predicate/function '{name}' starts with uppercase - consider using lowercase for consistency")

            # Check for reserved words
            if name in self.RESERVED:
                self.errors.append(f"'{name}' is a reserved keyword and cannot be used as a predicate/function")

    def _check_common_mistakes(self, formula: str):
        """Check for common syntax mistakes"""
        # Missing spaces around operators
        for op in ["->", "<->"]:
            # Check for operators without spaces
            pattern = rf"\w{re.escape(op)}\w"
            if re.search(pattern, formula):
                self.warnings.append(f"Consider adding spaces around '{op}' for readability")

        # Unquoted strings (should be predicates)
        if '"' in formula or "'" in formula:
            self.warnings.append("Strings in quotes are not standard in first-order logic - use predicates or constants instead")

        # Empty parentheses
        if "()" in formula:
            self.errors.append("Empty parentheses found - predicates and functions must have arguments")


def validate_formulas(formulas: List[str]) -> Dict[str, any]:
    """Validate a list of formulas

    Args:
        formulas: List of formulas to validate

    Returns:
        Dictionary with validation results
    """
    validator = SyntaxValidator()
    results = {"valid": True, "formula_results": []}

    for i, formula in enumerate(formulas):
        is_valid, errors, warnings = validator.validate(formula)

        formula_result = {"formula": formula, "valid": is_valid, "errors": errors, "warnings": warnings}

        results["formula_results"].append(formula_result)

        if not is_valid:
            results["valid"] = False

    return results


# Helper function to get helpful error messages
def get_syntax_help(error_type: str) -> str:
    """Get helpful message for common syntax errors"""
    help_messages = {
        "quantifier": """
Quantifier syntax: all variable (formula) or exists variable (formula)
Examples:
  - all x (man(x) -> mortal(x))
  - exists y (happy(y) & wise(y))
""",
        "implication": """
Implication syntax: premise -> conclusion
For multiple premises, use conjunction:
  - (premise1 & premise2) -> conclusion
  - all x ((p(x) & q(x)) -> r(x))
""",
        "parentheses": """
Parentheses must be balanced. Common mistakes:
  - Missing closing: all x (p(x) -> q(x)
  - Extra closing: all x (p(x) -> q(x)))
  - Missing around quantifier scope: all x p(x) -> q(x)  [should be: all x (p(x) -> q(x))]
""",
    }

    return help_messages.get(error_type, "No specific help available")
