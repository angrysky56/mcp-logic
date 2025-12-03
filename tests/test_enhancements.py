"""
Test the enhanced MCP Logic server functionality directly
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp_logic.mace4_wrapper import Mace4Wrapper
from mcp_logic.syntax_validator import validate_formulas
from mcp_logic.categorical_helpers import CategoricalHelpers


def test_mace4():
    """Test Mace4 model finding"""
    print("\n=== Testing Mace4 ===")

    ladr_path = Path(__file__).parent.parent / "ladr" / "bin"
    mace4 = Mace4Wrapper(ladr_path)

    # Test 1: Find a model for simple premises
    print("\nTest 1: Find model for P(a)")
    result = mace4.find_model(["P(a)"], domain_size=2)
    print(f"Result: {result['result']}")
    if result["result"] == "model_found":
        print(f"Domain size: {result['model']['domain_size']}")
        print("✓ Model finding works!")

    # Test 2: Find counterexample
    print("\nTest 2: Find counterexample - P(a) doesn't imply P(b)")
    result = mace4.find_counterexample(["P(a)"], "P(b)", domain_size=2)
    print(f"Result: {result['result']}")
    if result["result"] == "model_found":
        print("✓ Counterexample found!")
        print(f"Interpretation: {result.get('interpretation', 'N/A')}")


def test_syntax_validator():
    """Test syntax validation"""
    print("\n=== Testing Syntax Validator ===")

    # Test valid formula
    print("\nTest 1: Valid formula")
    result = validate_formulas(["all x (P(x) -> Q(x))"])
    print(f"Valid: {result['valid']}")
    print(f"Errors: {result['formula_results'][0]['errors']}")
    print(f"Warnings: {result['formula_results'][0]['warnings']}")

    # Test invalid formula (unbalanced parens)
    print("\nTest 2: Invalid formula (unbalanced parens)")
    result = validate_formulas(["all x (P(x) -> Q(x)"])
    print(f"Valid: {result['valid']}")
    print(f"Errors: {result['formula_results'][0]['errors']}")

    if not result["valid"]:
        print("✓ Syntax validation working!")


def test_categorical_helpers():
    """Test categorical reasoning helpers"""
    print("\n=== Testing Categorical Helpers ===")

    helpers = CategoricalHelpers()

    # Test 1: Get category axioms
    print("\nTest 1: Category axioms")
    axioms = helpers.category_axioms()
    print(f"Generated {len(axioms)} category axioms")
    print(f"First axiom: {axioms[0][:80]}...")
    print("✓ Category axioms generated!")

    # Test 2: Functor axioms
    print("\nTest 2: Functor axioms")
    axioms = helpers.functor_axioms("F")
    print(f"Generated {len(axioms)} functor axioms")
    print(f"Functor preserves identity: {axioms[0][:60]}...")
    print("✓ Functor axioms generated!")

    # Test 3: Commutativity verification
    print("\nTest 3: Commutativity diagram")
    premises, conclusion = helpers.verify_commutativity(path_a=["f", "g"], path_b=["h"], object_start="A", object_end="C")
    print(f"Generated {len(premises)} premises")
    print(f"Conclusion: {conclusion}")
    print("✓ Commutativity verification working!")


if __name__ == "__main__":
    print("Testing Enhanced MCP Logic Server Components")
    print("=" * 50)

    try:
        test_syntax_validator()
    except Exception as e:
        print(f"✗ Syntax validator test failed: {e}")

    try:
        test_categorical_helpers()
    except Exception as e:
        print(f"✗ Categorical helpers test failed: {e}")

    try:
        test_mace4()
    except Exception as e:
        print(f"✗ Mace4 test failed: {e}")

    print("\n" + "=" * 50)
    print("Testing complete!")
