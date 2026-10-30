"""PF-1 to PF-4 as Hypothesis property tests over the shipped reader (src/egrit_preflight/contract.py, outcomes.py).

Run: PYTHONPATH=src HYPOTHESIS_PROFILE=dev python3 -m unittest assurance.preflight.test_properties -v

Known defects are pinned on separate methods marked `expectedFailure`, each with the minimal input as an `@example`,
so the suite is green while they stand and reports "unexpected success" the day they are fixed. The general
properties no longer `assume` any input shape away: the two TypeError shapes (#31) and the unchecked uncertainty
records (#32) were fixed, and one pin is left, the scalar `attestations` gap of PF-4's strict sub-tree clause.
Nothing here is a proof: a pass is "no counterexample found under the profile's settings".
"""

import copy
import json
import unittest

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

import assurance.preflight  # noqa: F401  (registers the profiles and puts src/ on the path)
from assurance.preflight import generators as gen
from egrit_preflight import contract, outcomes

RANK = {"PASS": 0, "UNKNOWN": 1, "FAIL": 2}
ENUMS = {"outcome": contract.OUTCOMES, "evidence": contract.EVIDENCE, "overall": contract.OVERALL}


def fixture(name="pass-observed.json"):
    return dict(gen.valid_fixtures())[name]


def with_outcome_list():
    doc = fixture()
    doc["checks"][0]["outcome"] = []
    return doc


def with_mixed_requires_hardware():
    doc = fixture()
    doc["requires_hardware"] = [1, "a"]
    return doc


def with_verified_uncertainty():
    doc = fixture()
    doc["uncertainties"][0]["outcome"] = "VERIFIED"
    return doc


def with_scalar_uncertainty():
    doc = fixture()
    doc["uncertainties"][0] = ""
    return doc


def with_scalar_attestations():
    doc = fixture()
    doc["image"]["provenance"]["attestations"] = ""
    return doc


def leaves(value, prefix=()):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from leaves(v, prefix + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from leaves(v, prefix + (i,))
    else:
        yield prefix, value


def allow_at(path, allow=contract.ALLOWLIST):
    """The allowlist node this path leads to, or None when the path leaves the allowlist."""
    for step in path:
        if allow is True:
            return True
        if isinstance(allow, dict):
            if step not in allow:
                return None
            allow = allow[step]
        elif isinstance(allow, list):
            if not isinstance(step, int):
                return None
            allow = allow[0]
        else:
            return None
    return allow


def shape_differs(value, allow):
    """_pick returns None exactly here: the allowlist expects an object or an array and the document has neither."""
    return (isinstance(allow, dict) and not isinstance(value, dict)) or \
           (isinstance(allow, list) and not isinstance(value, list))


class PF1Headline(unittest.TestCase):
    """If load_report accepts, the document claims nothing this tool cannot have verified."""

    @given(gen.reports())
    def test_accepted_implies_headline(self, doc):
        got, problems = contract.load_report(gen.serialised(doc))
        if got is None:
            self.assertTrue(problems)
            return
        self.assertIs(got["hardware_verified"], False)
        image = got.get("image")
        if isinstance(image, dict) and isinstance(image.get("provenance"), dict):
            self.assertIs(image["provenance"]["signature_verified"], False)
        for c in got["checks"]:
            if c["id"] == "jetson.gpu":
                self.assertEqual(c["outcome"], "REQUIRES_HARDWARE")
                self.assertEqual(c["evidence"], "none")  # #44
        self.assertTrue(got["checks"])  # #45: a report that checked nothing is never accepted
        self.assertIn("jetson.gpu", {c["id"] for c in got["checks"]})
        self.assertIn("jetson.gpu", got["requires_hardware"])
        self.assertEqual(got["overall"], outcomes.overall(got["checks"]))
        self.assertEqual(sorted(got["requires_hardware"]),
                         sorted({c["id"] for c in got["checks"] if c["outcome"] == "REQUIRES_HARDWARE"}))

    def test_fixtures_agree(self):
        for name, doc in gen.valid_fixtures():
            self.assertEqual(contract.check_report(doc), [], name)
        for name, raw in gen.invalid_fixtures():
            self.assertIsNone(contract.load_report(raw)[0], name)


class PF2FailClosedTotal(unittest.TestCase):
    """load_report never raises and returns (None, problems) exactly when problems is non-empty."""

    @given(gen.raw_bytes())
    def test_raw_bytes_never_raise(self, raw):
        got, problems = contract.load_report(raw)
        self.assertEqual(got is None, bool(problems))

    @given(st.one_of(gen.json_trees(), gen.reports()))
    def test_json_values_never_raise(self, value):
        problems = contract.check_report(value)
        self.assertIsInstance(problems, list)
        got, problems2 = contract.load_report(gen.serialised(value))
        self.assertEqual(got is None, bool(problems2))
        self.assertEqual(bool(problems), bool(problems2))

    @settings(suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large], max_examples=6)
    @given(gen.near_limit())
    def test_near_the_byte_limit(self, item):
        name, delta, raw = item
        got, problems = contract.load_report(raw)
        if delta > 0:
            self.assertIsNone(got, (name, delta))
            self.assertEqual(problems, [f"report is larger than {contract.MAX_REPORT_BYTES} bytes"])
        else:
            self.assertIsNotNone(got, (name, delta, problems))

    def test_fixed_outcome_list_is_rejected(self):
        """Was a TypeError (egrit-preflight #31): checks[0].outcome = [] is now rejected, not raised."""
        got, problems = contract.load_report(gen.serialised(with_outcome_list()))
        self.assertIsNone(got)
        self.assertTrue(any("outcome must be one of" in p for p in problems), problems)

    def test_fixed_mixed_requires_hardware_is_rejected(self):
        """Was a TypeError (egrit-preflight #31): requires_hardware = [1, "a"] is now rejected, not raised."""
        got, problems = contract.load_report(gen.serialised(with_mixed_requires_hardware()))
        self.assertIsNone(got)
        self.assertIn("requires_hardware must be an array of strings", problems)


class PF3Overall(unittest.TestCase):
    """overall is the maximum of FAIL > UNKNOWN > PASS, monotone under append, REQUIRES_HARDWARE inert."""

    words = st.lists(st.sampled_from(contract.OUTCOMES), max_size=200)

    @staticmethod
    def checks(words):
        return [{"id": f"c{i}", "section": "doctor", "outcome": w, "evidence": "none", "summary": ""}
                for i, w in enumerate(words)]

    @given(words)
    def test_is_max(self, words):
        ranked = [RANK[w] for w in words if w in RANK]
        expected = "PASS" if not ranked else ("PASS", "UNKNOWN", "FAIL")[max(ranked)]
        self.assertEqual(outcomes.overall(self.checks(words)), expected)

    @given(words, words)
    def test_monotone_under_append(self, xs, ys):
        self.assertGreaterEqual(RANK[outcomes.overall(self.checks(xs + ys))], RANK[outcomes.overall(self.checks(xs))])

    @given(words)
    def test_requires_hardware_inert(self, words):
        self.assertEqual(outcomes.overall(self.checks(words + ["REQUIRES_HARDWARE"])),
                         outcomes.overall(self.checks(words)))

    @given(words, st.sampled_from(contract.OVERALL))
    def test_invariants_accept_overall_iff_equal(self, words, claimed):
        checks = self.checks(words)
        hardware = sorted(c["id"] for c in checks if c["outcome"] == "REQUIRES_HARDWARE")
        problems = contract._invariants({"overall": claimed, "requires_hardware": hardware}, checks)
        self.assertEqual(any(p.startswith("overall is") for p in problems), claimed != outcomes.overall(checks))


class PF4ViewNeverStrengthens(unittest.TestCase):
    """allowlisted_view is a sub-tree of the document, refuses what check_report refuses, and exports enum words only."""

    @given(gen.reports())
    def test_subtree_and_refusal(self, doc):
        """Every leaf of the view is the document's value at that path, or None where the document's shape differs
        from the allowlist (an object or array expected, something else found); no path leaves the allowlist."""
        problems = contract.check_report(doc)
        if problems:
            with self.assertRaises(contract.Rejected):
                contract.allowlisted_view(doc)
            return
        view = contract.allowlisted_view(copy.deepcopy(doc))
        for path, leaf in leaves(view):
            allow = allow_at(path)
            self.assertIsNotNone(allow, path)
            original = gen.get_at(doc, path)
            if leaf != original:
                self.assertIsNone(leaf, path)
                self.assertTrue(shape_differs(original, allow), (path, original))
        json.dumps(view)  # the view is still plain JSON

    @given(gen.reports())
    def test_exported_enum_leaves_are_in_the_enums(self, doc):
        if contract.check_report(doc):
            return
        for path, leaf in leaves(contract.allowlisted_view(doc)):
            if path and path[-1] in ENUMS:
                self.assertIn(leaf, ENUMS[path[-1]], path)

    def test_fixed_uncertainty_outcome_is_rejected(self):
        """Was accepted and exported (egrit-preflight #32): uncertainties[0].outcome = "VERIFIED" is now rejected."""
        doc = with_verified_uncertainty()
        self.assertTrue(any("uncertainties[0].outcome must be one of" in p for p in contract.check_report(doc)))
        with self.assertRaises(contract.Rejected):
            contract.allowlisted_view(doc)

    def test_fixed_scalar_uncertainty_is_rejected(self):
        """Was accepted with a None leaf in the view (egrit-preflight #32): uncertainties[0] = "" is now rejected."""
        self.assertIn("uncertainties[0] must be an object", contract.check_report(with_scalar_uncertainty()))

    @unittest.expectedFailure
    @example(with_scalar_attestations())
    @given(st.just(with_scalar_attestations()))
    def test_known_gap_strict_subtree(self, doc):
        """Pinned: image.provenance.attestations = "" is accepted, and the view holds None at that path, a leaf the
        document does not have. The strict sub-tree clause of PF-4 fails on it. (uncertainties[0] = "" was the other
        case; rule 10 rejects it since #32.)"""
        self.assertEqual(contract.check_report(doc), [])
        for path, leaf in leaves(contract.allowlisted_view(doc)):
            self.assertEqual(leaf, gen.get_at(doc, path), path)


if __name__ == "__main__":
    unittest.main()
