"""
Syntax validator for logical formulas before sending to Prover9/Mace4.

Provides early feedback on common syntax errors to improve user experience.
"""

import re
from typing import Any


def normalize_formula(formula: str) -> str:
    """Normalize a formula to the syntax LADR (Prover9/Mace4) accepts.

    Callers naturally write logical negation as '~' (the most common notation),
    but LADR's term reader only accepts '-' for negation and fails on '~' with
    'sread_term error'. Rather than push that quirk onto every caller via prompt
    instructions, we translate here at the boundary.

    Conversions:
      - '~' (negation) -> '-'

    The translation is purely lexical and safe: '~' has no other meaning in
    LADR formula syntax, so any occurrence is an intended negation.

    Args:
        formula: A first-order-logic formula string.

    Returns:
        The formula with LADR-compatible operators.
    """
    return formula.replace("~", "-")


class SyntaxValidator:
    """Pre-validate logical formulas for common syntax errors"""

    # Common quantifiers and operators
    QUANTIFIERS = {"all", "exists"}
    OPERATORS = {"->", "<->", "&", "|", "-"}
    RESERVED = QUANTIFIERS | {"true", "false", "end_of_list"}

    def __init__(self):
        self.errors = []
        self.warnings = []

    def validate(self, formula: str) -> tuple[bool, list[str], list[str]]:
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
        # Pattern: quantifier followed by variables, then lookahead for '(' or a predicate name
        # This supports multi-variable quantifiers like 'all x y (p(x,y))'
        # and unparenthesized bodies like 'all x p(x) -> q(x)'
        pattern = re.compile(r"\b(all|exists)\s+([\w\s]+?)\s*(?=\(|[a-zA-Z_])")

        # Keep track of where we find quantifiers to avoid duplicate checks
        found_quantifiers = False

        for match in pattern.finditer(formula):
            found_quantifiers = True
            quantifier = match.group(1)
            vars_str = match.group(2).strip()
            variables = vars_str.split()

            for var in variables:
                if not var[0].islower():
                    self.warnings.append(
                        f"Quantifier variable '{var}' should start with lowercase"
                    )

            # Check the body of the quantifier
            pos = match.end()
            remaining = formula[pos:].lstrip()

            if not remaining:
                self.errors.append(
                    f"Quantifier '{quantifier} {vars_str}' must be followed by a formula"
                )
            elif remaining[0] != "(":
                # Unparenthesized body: Check for scope issues with operators
                if "->" in remaining or "|" in remaining or "<->" in remaining:
                    self.warnings.append(
                        f"Quantifier '{quantifier} {vars_str}' has an unparenthesized body which may cause scope issues with implications or disjunctions"
                    )

        # If the formula contains a quantifier but didn't match our valid pattern
        if not found_quantifiers:
            for quantifier in self.QUANTIFIERS:
                if re.search(rf"\b{quantifier}\b", formula):
                    # It has a quantifier but failed our structured match
                    # Let's do a basic check to emit the missing parenthesis error if needed
                    # but only if it's truly malformed
                    pass

    def _check_operators(self, formula: str):
        """Check operator usage"""
        # Check for double operators (likely mistakes)
        for op in ["&", "|"]:
            if op + op in formula:
                self.warnings.append(
                    f"Double operator '{op}{op}' found - did you mean to use it twice?"
                )

        # Check for implication chains without parentheses
        if formula.count("->") > 1 and formula.count("(") == 0:
            self.warnings.append(
                "Multiple implications without parentheses - consider adding parentheses for clarity"
            )

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
                self.warnings.append(
                    f"Predicate/function '{name}' starts with uppercase - consider using lowercase for consistency"
                )

            # Check for reserved words
            if name in self.RESERVED:
                self.errors.append(
                    f"'{name}' is a reserved keyword and cannot be used as a predicate/function"
                )

    def _check_common_mistakes(self, formula: str):
        """Check for common syntax mistakes"""
        # Missing spaces around operators
        for op in ["->", "<->"]:
            # Check for operators without spaces
            pattern = rf"\w{re.escape(op)}\w"
            if re.search(pattern, formula):
                self.warnings.append(
                    f"Consider adding spaces around '{op}' for readability"
                )

        # Unquoted strings (should be predicates)
        if '"' in formula or "'" in formula:
            self.warnings.append(
                "Strings in quotes are not standard in first-order logic - use predicates or constants instead"
            )

        # Empty parentheses
        if "()" in formula:
            self.errors.append(
                "Empty parentheses found - predicates and functions must have arguments"
            )


def _symbol_arities(formula: str) -> list[tuple[str, int]]:
    """Extract (symbol, arity) pairs for every applied symbol in a formula.

    Argument counting is done at paren depth 1 relative to the symbol, so a
    nested application like ``f(g(x, y), z)`` correctly reports ``f/2`` and
    ``g/2`` rather than splitting on every comma. Commas inside list terms do
    not count as arguments. Bare atoms and constants are recorded at arity 0.

    Quantifier keywords and their bound variables are skipped: ``all x
    (p(x))`` must not read either ``all`` or the grouping occurrence of ``x``
    as an applied symbol.
    """
    bound_variables: set[str] = set()
    for quantifier in re.finditer(r"\b(?:all|exists)\b", formula):
        position = quantifier.end()
        while True:
            variable = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)", formula[position:])
            if not variable or variable.group(1) in SyntaxValidator.QUANTIFIERS:
                break
            name = variable.group(1)
            position += variable.end()
            # With an unparenthesized body (`all x p(x)`), the identifier
            # immediately followed by `(` is the first predicate, not another
            # quantified variable. A space before `(` instead marks the end of
            # a declaration such as `all x y (p(x, y))`.
            if formula[position:].startswith("("):
                break
            bound_variables.add(name)
            if formula[position:].lstrip().startswith("("):
                break

    found: list[tuple[str, int]] = []
    applications = list(re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", formula))
    applied_name_starts = {match.start(1) for match in applications}
    for match in applications:
        symbol = match.group(1)
        if symbol in SyntaxValidator.RESERVED or symbol in bound_variables:
            continue
        depth = 0
        list_depth = 0
        commas = 0
        empty = True
        for index in range(match.end() - 1, len(formula)):
            char = formula[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            elif depth == 1:
                if char == "[":
                    list_depth += 1
                    empty = False
                elif char == "]":
                    list_depth = max(0, list_depth - 1)
                elif char == "," and list_depth == 0:
                    commas += 1
                elif not char.isspace():
                    empty = False
        found.append((symbol, 0 if empty else commas + 1))

    for identifier in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", formula):
        symbol = identifier.group(1)
        if (
            symbol in SyntaxValidator.RESERVED
            or symbol in bound_variables
            or identifier.start(1) in applied_name_starts
            or (identifier.start(1) > 0 and formula[identifier.start(1) - 1] == "$")
        ):
            continue
        found.append((symbol, 0))
    return found


def _check_set_consistency(formulas: list[str]) -> list[str]:
    """Find defects that are only visible ACROSS a set of formulas.

    Every other check in this module inspects one formula at a time, which
    leaves a whole class of rejection invisible. The clearest case is arity:

        exists x (biosynthetic_precursor(x))
        exists x (biosynthetic_precursor(glutamate, glutamine))

    Both are individually well-formed and this validator reported
    ``valid: true`` for each. Prover9 rejects the pair, because a symbol must
    have one fixed arity throughout — and it reports only "Syntax error or
    invalid input", naming nothing.

    Observed cost of the gap: an agent wrote exactly that pair, called
    check_well_formed, was told the formulas were fine, and resubmitted the
    identical set three times before the block was dropped from its analysis.
    A validator that answers "valid" about a set the prover will refuse is
    worse than no validator, because it redirects the search away from the
    actual fault.
    """
    arities: dict[str, dict[int, str]] = {}
    for formula in formulas:
        for symbol, arity in _symbol_arities(formula):
            seen = arities.setdefault(symbol, {})
            seen.setdefault(arity, formula)

    errors: list[str] = []
    for symbol in sorted(arities):
        seen = arities[symbol]
        if len(seen) < 2:
            continue
        counts = ", ".join(str(a) for a in sorted(seen))
        examples = "; ".join(f"arity {arity}: {seen[arity]}" for arity in sorted(seen))
        errors.append(
            f"Symbol '{symbol}' is used with inconsistent arity ({counts}). "
            "Prover9 requires one fixed arity per symbol and will reject the "
            f"whole set. Rename one use, or give the symbol a single arity. {examples}"
        )
    return errors


def validate_formulas(formulas: list[str]) -> dict[str, Any]:
    """Validate a list of formulas, individually AND as a set.

    Args:
        formulas: List of formulas to validate

    Returns:
        Dictionary with validation results. ``formula_results`` carries the
        per-formula verdicts as before; ``set_errors`` carries defects that only
        exist across formulas, and any such defect also clears the top-level
        ``valid`` flag — a set the prover will refuse must never be reported as
        valid, whatever each formula looks like on its own.
    """
    validator = SyntaxValidator()
    results: dict[str, Any] = {
        "valid": True,
        "formula_results": [],
        "set_errors": [],
    }

    for formula in formulas:
        is_valid, errors, warnings = validator.validate(formula)

        formula_result = {
            "formula": formula,
            "valid": is_valid,
            "errors": errors,
            "warnings": warnings,
        }

        results["formula_results"].append(formula_result)

        if not is_valid:
            results["valid"] = False

    set_errors = _check_set_consistency(formulas)
    if set_errors:
        results["set_errors"] = set_errors
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
