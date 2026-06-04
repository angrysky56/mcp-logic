"""Regression tests for the vacuity guard in Mace4Wrapper.

A universally-quantified conditional ``all x (P(x) -> Q(x))`` is vacuously
true over an empty domain, so Mace4 can return an all-false ("empty world")
model that satisfies almost any set of conditionals. ``_assess_vacuity``
flags that degenerate case so callers do not mistake vacuous satisfaction
for substantive consistency. See ``skills/mcp-logic/SKILL.md`` ("Empty-World
Trap") and the AGEM biosemiotics run that motivated this guard.
"""

from mcp_logic.mace4_wrapper import Mace4Wrapper


def test_empty_world_is_flagged_vacuous():
    """All predicates false everywhere -> is_vacuous, with a guidance note."""
    model = {
        "predicates": {
            "organism": ["0", "0", "0"],
            "machine": ["0", "0", "0"],
            "semiosis": ["0", "0", "0"],
        }
    }
    v = Mace4Wrapper._assess_vacuity(model)
    assert v["is_vacuous"] is True
    assert "note" in v
    assert v["nonempty_predicates"] == []


def test_one_true_tuple_is_not_vacuous():
    """Any predicate that holds somewhere -> not vacuous."""
    model = {"predicates": {"organism": ["1", "0", "0"], "machine": ["0", "0", "0"]}}
    v = Mace4Wrapper._assess_vacuity(model)
    assert v["is_vacuous"] is False
    assert v["empty_predicates"] == ["machine"]
    assert v["nonempty_predicates"] == ["organism"]
    assert "note" not in v


def test_no_predicates_is_not_flagged():
    """Models with only functions/constants are not flagged vacuous."""
    assert Mace4Wrapper._assess_vacuity({"predicates": {}})["is_vacuous"] is False


def test_truth_tokens_are_case_insensitive():
    """'false'/'F'/'0' all count as false; a '1' anywhere is a positive fact."""
    model = {"predicates": {"p": ["false", "F", "0"], "q": ["0", "1", "0"]}}
    v = Mace4Wrapper._assess_vacuity(model)
    assert v["is_vacuous"] is False
    assert v["empty_predicates"] == ["p"]
    assert v["nonempty_predicates"] == ["q"]


def test_parse_model_attaches_vacuity():
    """_parse_model attaches a 'vacuity' assessment on a real interpretation."""
    sample = (
        "DOMAIN SIZE 3\n"
        "interpretation( 3, [number=1, seconds=0], [\n"
        "        relation(organism(_), [ 0, 0, 0 ]),\n"
        "        relation(machine(_), [ 0, 0, 0 ])\n"
        "]).\n"
    )
    inst = Mace4Wrapper.__new__(Mace4Wrapper)  # skip __init__ (needs the binary)
    parsed = inst._parse_model(sample)
    assert parsed["predicates"] == {
        "organism": ["0", "0", "0"],
        "machine": ["0", "0", "0"],
    }
    assert parsed["vacuity"]["is_vacuous"] is True
