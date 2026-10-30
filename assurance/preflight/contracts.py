"""CrossHair harnesses over the shipped functions. The first assert in each function is its precondition; the asserts
after the call are postconditions. CrossHair (Z3 behind it) searches for inputs that satisfy the precondition and
break a postcondition, within a per-condition timeout.

Run: PYTHONPATH=src crosshair check assurance/preflight/contracts.py --analysis_kind=asserts --per_condition_timeout=60

The functions take the simplest types CrossHair can reason about. `check_report_is_total` therefore quantifies over a
family of documents shaped like a report, not over every JSON value; the Hypothesis suite covers the rest.
"""

from typing import Dict, List, Union

from egrit_preflight import contract, outcomes

OUTCOMES = ("PASS", "FAIL", "UNKNOWN", "REQUIRES_HARDWARE")
RANK = {"PASS": 0, "UNKNOWN": 1, "FAIL": 2}


def _reference_overall(words: List[str]) -> str:
    best = 0
    for w in words:
        if w in RANK and RANK[w] > best:
            best = RANK[w]
    return ("PASS", "UNKNOWN", "FAIL")[best]


def overall_is_max(words: List[str]) -> str:
    """PF-3: outcomes.overall is the maximum of FAIL > UNKNOWN > PASS and REQUIRES_HARDWARE is inert."""
    assert all(w in OUTCOMES for w in words)
    result = outcomes.overall([{"outcome": w} for w in words])
    assert result == _reference_overall(words)
    assert outcomes.overall([{"outcome": w} for w in words] + [{"outcome": "REQUIRES_HARDWARE"}]) == result
    return result


def invariants_accept_overall_iff_equal(words: List[str], claimed: str) -> bool:
    """PF-3: contract._invariants raises an overall problem exactly when the claim differs from the checks."""
    assert all(w in OUTCOMES for w in words)
    assert claimed in ("PASS", "FAIL", "UNKNOWN")
    checks = [{"id": "c" + str(i), "outcome": w, "evidence": "none"} for i, w in enumerate(words)]
    hardware = sorted(c["id"] for c in checks if c["outcome"] == "REQUIRES_HARDWARE")
    problems = contract._invariants({"overall": claimed, "requires_hardware": hardware}, checks)
    complained = any(p.startswith("overall is") for p in problems)
    assert complained == (claimed != _reference_overall(words))
    return complained


Leaf = Union[int, str, bool, None]
SmallDoc = Dict[str, Union[Leaf, Dict[str, Leaf], List[Dict[str, Leaf]]]]
SMALL_ALLOW = {"a": True, "b": {"c": True}, "d": [{"e": True}]}


def pick_is_subtree(value: SmallDoc) -> dict:
    """PF-4: _pick returns a sub-tree of its input: every key present came from the input with the same value."""
    assert isinstance(value, dict)
    view = contract._pick(value, SMALL_ALLOW)
    assert isinstance(view, dict)
    assert set(view) <= set(value)
    assert "a" not in view or view["a"] == value["a"]
    if "b" in view and view["b"] is not None:
        assert isinstance(value["b"], dict) and set(view["b"]) <= {"c"}
        assert "c" not in view["b"] or view["b"]["c"] == value["b"]["c"]
    if "d" in view and view["d"] is not None:
        assert isinstance(value["d"], list) and len(view["d"]) == len(value["d"])
        for got, orig in zip(view["d"], value["d"]):
            assert got is None or (isinstance(orig, dict) and set(got) <= {"e"})
    return view


Check = Dict[str, Union[str, List[str], None]]
Report = Dict[str, Union[str, bool, int, None, List[Check], List[Union[str, int]], Dict[str, Union[str, bool, None]]]]


def check_report_is_total(doc: Report) -> list:
    """PF-2: check_report returns a list of strings for a report-shaped document and never raises."""
    assert isinstance(doc, dict)
    problems = contract.check_report(doc)
    assert isinstance(problems, list)
    assert all(isinstance(p, str) for p in problems)
    return problems


def accepted_implies_headline(doc: Report) -> bool:
    """PF-1: when check_report accepts, hardware_verified is False and every jetson.gpu check is REQUIRES_HARDWARE."""
    assert isinstance(doc, dict)
    problems = contract.check_report(doc)
    if problems:
        return False
    assert doc.get("hardware_verified") is False
    checks = doc.get("checks")
    assert isinstance(checks, list)
    for c in checks:
        assert isinstance(c, dict)
        assert c.get("outcome") in OUTCOMES
        assert c.get("id") != "jetson.gpu" or c.get("outcome") == "REQUIRES_HARDWARE"
    assert doc.get("overall") == outcomes.overall(checks)
    return True
