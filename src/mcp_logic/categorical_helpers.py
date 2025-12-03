"""
Categorical reasoning helpers for translating categorical properties to FOL.

Provides utilities for working with category theory concepts in first-order logic.
"""

from typing import List, Dict, Tuple


class CategoricalHelpers:
    """Helper functions for categorical reasoning in first-order logic"""

    @staticmethod
    def category_axioms() -> List[str]:
        """Generate basic category theory axioms

        Returns:
            List of FOL axioms defining a category
        """
        return [
            # Identity morphisms exist
            "all x (object(x) -> exists i (morphism(i) & source(i,x) & target(i,x) & identity(i,x)))",
            # Identity is unique
            "all x all i1 all i2 ((identity(i1,x) & identity(i2,x)) -> i1 = i2)",
            # Composition exists when source/target match
            "all f all g ((morphism(f) & morphism(g) & target(f) = source(g)) -> exists h (morphism(h) & compose(g,f,h)))",
            # Composition is associative
            "all f all g all h all fg all gh all fgh all gfh ((compose(g,f,fg) & compose(h,g,gh) & compose(h,fg,fgh) & compose(gh,f,gfh)) -> fgh = gfh)",
            # Left identity law
            "all f all a all id ((morphism(f) & source(f,a) & identity(id,a) & compose(f,id,comp)) -> comp = f)",
            # Right identity law
            "all f all b all id ((morphism(f) & target(f,b) & identity(id,b) & compose(id,f,comp)) -> comp = f)",
        ]

    @staticmethod
    def functor_axioms(functor_name: str = "F") -> List[str]:
        """Generate functor axioms

        Args:
            functor_name: Name of the functor (default: F)

        Returns:
            List of FOL axioms defining a functor
        """
        f = functor_name.lower()
        return [
            # Functor preserves identity
            f"all x all id (identity(id,x) -> identity({f}(id), {f}(x)))",
            # Functor preserves composition
            f"all g all h all gh ((compose(g,h,gh)) -> compose({f}(g), {f}(h), {f}(gh)))",
        ]

    @staticmethod
    def verify_commutativity(path_a: List[str], path_b: List[str], object_start: str, object_end: str) -> Tuple[List[str], str]:
        """Generate FOL to verify diagram commutativity

        Two paths in a diagram commute if composing morphisms along each path
        yields the same result.

        Args:
            path_a: List of morphism names in first path
            path_b: List of morphism names in second path
            object_start: Starting object
            object_end: Ending object

        Returns:
            Tuple of (premises, conclusion) for proving commutativity
        """
        premises = []

        # Define morphisms in path A
        for i, morph in enumerate(path_a):
            if i == 0:
                premises.append(f"morphism({morph})")
                premises.append(f"source({morph}, {object_start})")
            else:
                premises.append(f"morphism({morph})")

            if i == len(path_a) - 1:
                premises.append(f"target({morph}, {object_end})")

        # Define morphisms in path B
        for i, morph in enumerate(path_b):
            if i == 0:
                premises.append(f"morphism({morph})")
                premises.append(f"source({morph}, {object_start})")
            else:
                premises.append(f"morphism({morph})")

            if i == len(path_b) - 1:
                premises.append(f"target({morph}, {object_end})")

        # Compose paths
        comp_a = _compose_path_helper(path_a, "comp_a")
        comp_b = _compose_path_helper(path_b, "comp_b")

        premises.extend(comp_a["premises"])
        premises.extend(comp_b["premises"])

        # Conclusion: composed paths are equal
        conclusion = f"{comp_a['result']} = {comp_b['result']}"

        return (premises, conclusion)

    @staticmethod
    def natural_transformation_condition(functor_f: str = "F", functor_g: str = "G", component: str = "alpha") -> List[str]:
        """Generate naturality condition for a natural transformation

        For natural transformation α: F ⇒ G, the naturality square must commute:
        For any morphism f: A → B,
        G(f) ∘ α_A = α_B ∘ F(f)

        Args:
            functor_f: First functor name
            functor_g: Second functor name
            component: Natural transformation component name

        Returns:
            List of FOL statements for naturality
        """
        f_lower = functor_f.lower()
        g_lower = functor_g.lower()

        return [
            # Naturality condition
            f"all morph all a all b ((morphism(morph) & source(morph,a) & target(morph,b)) -> exists comp1 exists comp2 (compose({g_lower}(morph), {component}(a), comp1) & compose({component}(b), {f_lower}(morph), comp2) & comp1 = comp2))"
        ]


def _compose_path_helper(path: List[str], result_name: str) -> Dict:
    """Helper to generate composition premises for a path

    Args:
        path: List of morphism names
        result_name: Name for the final composed morphism

    Returns:
        Dict with premises and result name
    """
    if len(path) == 1:
        return {"premises": [], "result": path[0]}

    premises = []
    current = path[0]

    for i in range(1, len(path)):
        temp_name = f"{result_name}_temp_{i}" if i < len(path) - 1 else result_name
        premises.append(f"compose({path[i]}, {current}, {temp_name})")
        current = temp_name

    return {"premises": premises, "result": current}


# Convenience functions for common categorical concepts


def monoid_axioms() -> List[str]:
    """Axioms for a monoid (category with one object)"""
    return [
        # Binary operation
        "all x all y exists z (mult(x,y,z))",
        # Associativity
        "all x all y all z all xy all yz all xyz all ybc ((mult(x,y,xy) & mult(y,z,yz) & mult(xy,z,xyz) & mult(x,yz,xyz2)) -> xyz = xyz2)",
        # Identity exists
        "exists e (all x (mult(e,x,x) & mult(x,e,x)))",
    ]


def group_axioms() -> List[str]:
    """Axioms for a group"""
    return monoid_axioms() + [
        # Inverses exist
        "all x exists y (mult(x,y,e) & mult(y,x,e))"
    ]
