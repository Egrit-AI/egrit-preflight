"""The vendor target profile (docs/vendor-target-profile.md): its reader, its validation matrix and its export.

Offline and deterministic. Every profile is synthetic (tests/make_profile_fixtures.py), Docker is scripted, nothing is
pulled and nothing runs on hardware. The tests pin down that a missing, contradicted or wrong-revision value can only
give UNKNOWN, that nothing is inherited between configurations, and that a profile adds nothing to a version 1 report.
"""

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from egrit_preflight import cli, contract, profile
from egrit_preflight.image import load_target
from tests import make_profile_fixtures
from tests.fakes import DIGEST, INFO_ARM, FakeRunner, docker_ok, image_inspect, inspect_rule, ok
from tests.jsonschema_lite import validate

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "profiles"
SCHEMA = json.loads((ROOT / "schema" / "vendor-target-profile.schema.json").read_text(encoding="utf-8"))
REPORT_SCHEMA = json.loads((ROOT / "schema" / "report.schema.json").read_text(encoding="utf-8"))
VERSIONS = ("jetpack", "jetson_linux", "cuda", "tensorrt")
SOFTWARE = tuple(f for f in profile.FACTS if f != "architecture")


def valid():
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((FIXTURES / "valid").glob("*.json"))}


def invalid():
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted((FIXTURES / "invalid").glob("*.json"))}


def outcomes(doc):
    return {c["id"]: c["outcome"] for c in profile.assess_profile(doc)["checks"]}


def report_with_target(record, tag="r36.4.0"):
    """A full v1 report for a pinned linux/arm64 L4T image compared with `record`, against a scripted Docker."""
    runner = FakeRunner([inspect_rule(ok(image_inspect("arm64"))), *docker_ok(INFO_ARM)])
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "target.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        with mock.patch("platform.system", return_value="Linux"), \
                mock.patch("platform.machine", return_value="aarch64"):
            code = cli.main(["report", "--json", "--image", f"nvcr.io/nvidia/l4t-base:{tag}@{DIGEST}",
                             "--target", str(path)], out=out, err=io.StringIO(), runner=runner)
    doc, problems = contract.load_report(out.getvalue())
    assert problems == [], problems
    return code, doc


def checks_by_id(report):
    found = {}
    for c in report["checks"]:
        found.setdefault(c["id"], []).append(c["outcome"])
    return found


class Fixtures(unittest.TestCase):
    def test_the_committed_fixtures_are_what_the_generator_produces(self):
        # Prevents a hand-edited fixture, or a generator change that never reached the files.
        built = make_profile_fixtures.build()
        on_disk = {str(p.relative_to(FIXTURES)): p.read_text(encoding="utf-8") for p in FIXTURES.rglob("*.json")}
        self.assertEqual(on_disk, built)

    def test_every_valid_fixture_is_accepted_by_the_reader_and_the_schema(self):
        self.assertGreaterEqual(len(valid()), 10)
        for name, doc in valid().items():
            self.assertEqual(profile.check_profile(doc), [], name)
            self.assertEqual(validate(doc, SCHEMA), [], name)
            loaded, problems = profile.load_profile(json.dumps(doc))
            self.assertEqual((loaded, problems), (doc, []), name)

    def test_every_invalid_fixture_is_rejected_whole(self):
        self.assertGreaterEqual(len(invalid()), 25)
        for name, text in invalid().items():
            doc, problems = profile.load_profile(text)
            self.assertIsNone(doc, name)
            self.assertTrue(problems, name)
            if name in ("truncated", "nan-constant"):  # refused as text, before there is a document to check
                continue
            for call in (profile.assess_profile, profile.to_target_record, lambda d: profile.resolve(d, "jetpack")):
                with self.assertRaises(ValueError, msg=name):
                    call(json.loads(text))

    def test_every_fixture_is_synthetic_and_names_no_real_vendor_or_host(self):
        for name, doc in valid().items():
            self.assertIs(doc["synthetic"], True, name)
            self.assertIn("(synthetic)", doc["identity"]["vendor"], name)
            urls = [s["source_url"] for statements in doc["facts"].values() for s in statements]
            urls += [e["source_url"] for e in doc.get("equivalences", [])]
            for url in filter(None, urls):
                self.assertTrue(url.startswith("https://vendor.example/"), f"{name}: {url}")

    def test_oversized_and_non_text_input_is_refused(self):
        self.assertIsNone(profile.load_profile(b" " * (profile.MAX_PROFILE_BYTES + 1))[0])
        self.assertIsNone(profile.load_profile(b"\xff\xfe")[0])
        self.assertIsNone(profile.load_profile("[" * 100000)[0])

    def test_provenance_keys_are_required_even_when_their_values_may_be_null(self):
        for evidence in ("declared", "observed", "none"):
            for key in ("evidence", "source_url", "retrieved"):
                for kind in ("statement", "equivalence"):
                    if kind == "equivalence" and evidence == "none":
                        continue
                    with self.subTest(evidence=evidence, key=key, kind=kind):
                        doc = copy.deepcopy(valid()["equivalence-scoped-to-two-fields"])
                        item = (doc["facts"]["jetpack"][0] if kind == "statement"
                                else doc["equivalences"][0])
                        item["evidence"] = evidence
                        if evidence == "observed":
                            item["source_url"] = None
                        elif evidence == "none":
                            item.update(value=None, source_url=None, retrieved=None)
                        self.assertEqual(profile.check_profile(doc), [])
                        self.assertEqual(validate(doc, SCHEMA), [])
                        del item[key]
                        self.assertTrue(validate(doc, SCHEMA))
                        loaded, problems = profile.load_profile(json.dumps(doc))
                        self.assertIsNone(loaded)
                        self.assertTrue(any(f".{key} is missing" in p for p in problems))
                        for call in (profile.assess_profile, profile.to_target_record,
                                     lambda d: profile.resolve(d, "jetpack"),
                                     lambda d: profile.equivalent(d, valid()["complete-declared"], ["jetpack"])):
                            with self.assertRaises(ValueError):
                                call(doc)


class ValidationMatrix(unittest.TestCase):
    """The matrix in docs/vendor-target-profile-design.md, one case each."""

    def setUp(self):
        self.docs = valid()

    def test_a_complete_declared_profile_is_complete_and_still_no_compatibility_result(self):
        result = profile.assess_profile(self.docs["complete-declared"])
        self.assertIs(result["complete"], True)
        self.assertIs(result["compatibility_established"], False)
        self.assertIs(result["hardware_verified"], False)
        passed = [c for c in result["checks"] if c["outcome"] == "PASS"]
        self.assertEqual([(c["id"], c["evidence"]) for c in passed], [("profile.architecture", "declared")])

    def test_a_missing_software_revision_leaves_every_fact_unknown_and_infers_no_tuple(self):
        doc = self.docs["missing-software-revision"]
        self.assertEqual(doc["facts"]["jetpack"][0]["value"], "6")  # the family-level claim is kept, not used
        got = outcomes(doc)
        for cid in ("profile.identity.software_revision", "profile.identity.hardware_revision",
                    *(f"profile.{f}" for f in profile.FACTS)):
            self.assertEqual(got[cid], "UNKNOWN", cid)
        record = profile.to_target_record(doc)
        self.assertNotIn("architecture", record)
        self.assertEqual({record["software"]["jetpack"], record["software"]["jetson_linux"],
                          record["runtimes"]["cuda"], record["runtimes"]["tensorrt"]}, {"not established"})

    def test_contradictory_declarations_are_unknown_and_both_sources_are_kept(self):
        doc = self.docs["contradictory-jetpack"]
        found = profile.resolve(doc, "jetpack")
        self.assertEqual((found["state"], found["value"]), ("contradictory", None))
        self.assertEqual(sorted(s["value"] for s in found["statements"]), ["6.1", "6.2"])
        [check] = [c for c in profile.assess_profile(doc)["checks"] if c["id"] == "profile.jetpack"]
        self.assertEqual(check["outcome"], "UNKNOWN")
        for s in found["statements"]:
            self.assertIn(s["source_url"], check["detail"])
        self.assertEqual(profile.to_target_record(doc)["software"]["jetpack"], "not established")

    def test_the_order_and_date_of_contradicting_sources_never_pick_a_winner(self):
        doc = self.docs["contradictory-jetpack"]
        for newer in (0, 1):
            edited = copy.deepcopy(doc)
            edited["facts"]["jetpack"][newer]["retrieved"] = "2027-01-01"
            edited["facts"]["jetpack"].reverse()
            self.assertEqual(profile.resolve(edited, "jetpack")["state"], "contradictory")

    def test_two_sources_that_agree_are_one_stated_value(self):
        doc = copy.deepcopy(self.docs["contradictory-jetpack"])
        doc["facts"]["jetpack"][1]["value"] = "6.2"
        found = profile.resolve(doc, "jetpack")
        self.assertEqual((found["state"], found["value"], len(found["statements"])), ("stated", "6.2", 2))

    def test_near_matches_are_not_merged(self):
        # 36.4 and 36.4.0 may or may not be the same release; the reader does not decide.
        doc = copy.deepcopy(self.docs["complete-declared"])
        doc["facts"]["jetson_linux"].append(dict(doc["facts"]["jetson_linux"][0], value="36.4"))
        self.assertEqual(profile.resolve(doc, "jetson_linux")["state"], "contradictory")

    def test_a_wrong_architecture_fails_against_linux_arm64(self):
        doc = self.docs["wrong-architecture"]
        result = profile.assess_profile(doc)
        self.assertEqual(outcomes(doc)["profile.architecture"], "FAIL")
        self.assertIs(result["complete"], False)
        code, report = report_with_target(profile.to_target_record(doc))
        self.assertEqual(checks_by_id(report)["target.architecture"], ["FAIL"])
        self.assertEqual((report["overall"], code), ("FAIL", 1))

    def test_an_absent_abi_is_unknown_whatever_else_is_stated(self):
        doc = self.docs["abi-absent"]
        got = outcomes(doc)
        self.assertEqual(got["profile.abi"], "UNKNOWN")
        self.assertEqual(got["profile.architecture"], "PASS")
        self.assertIs(profile.assess_profile(doc)["complete"], False)

    def test_a_custom_os_inherits_no_abi_from_its_module_or_jetpack(self):
        doc = self.docs["abi-absent"]
        self.assertTrue(doc["identity"]["module"].startswith("jetson-"))
        self.assertEqual(profile.resolve(doc, "jetpack")["state"], "stated")
        self.assertEqual(profile.resolve(doc, "abi"), {"state": "missing", "value": None, "statements": [],
                                                       "set_aside": 0})

    def test_statements_about_another_revision_are_set_aside_not_merged(self):
        doc = self.docs["other-revision-only"]
        self.assertNotEqual(doc["identity"]["hardware_revision"],
                            doc["facts"]["jetpack"][0]["applies_to"]["hardware_revision"])
        for fact in profile.FACTS:
            found = profile.resolve(doc, fact)
            self.assertEqual((found["state"], found["set_aside"]), ("missing", 1), fact)
        self.assertIs(profile.assess_profile(doc)["complete"], False)
        self.assertNotIn("PASS", outcomes(doc).values())

    def test_the_gpu_and_every_required_interface_always_need_hardware(self):
        for name, doc in self.docs.items():
            got = outcomes(doc)
            self.assertEqual(got["profile.gpu"], "REQUIRES_HARDWARE", name)
            for interface in doc["required_interfaces"]:
                self.assertEqual(got[f"profile.interface.{interface}"], "REQUIRES_HARDWARE", name)

    def test_observed_statements_change_no_outcome_and_verify_no_hardware(self):
        observed, declared = self.docs["observed-statements"], self.docs["complete-declared"]
        self.assertTrue(all(s["evidence"] == "observed" for st in observed["facts"].values() for s in st))
        self.assertEqual(profile.assess_profile(observed), profile.assess_profile(declared))
        self.assertIs(profile.assess_profile(observed)["hardware_verified"], False)

    def test_no_profile_ever_reports_compatibility_or_a_pass_beyond_declared_architecture(self):
        for name, doc in self.docs.items():
            result = profile.assess_profile(doc)
            self.assertIs(result["compatibility_established"], False, name)
            self.assertIs(result["hardware_verified"], False, name)
            for c in result["checks"]:
                self.assertIn(c["outcome"], contract.OUTCOMES, name)
                self.assertNotEqual(c["evidence"], "observed", f"{name}: {c['id']}")
                if c["outcome"] == "PASS":
                    self.assertEqual(c["id"], "profile.architecture", name)

    def test_only_a_fully_stated_profile_is_complete(self):
        complete = {n for n, d in self.docs.items() if profile.assess_profile(d)["complete"]}
        self.assertEqual(complete, {"complete-declared", "later-software-revision", "observed-statements",
                                    "equivalence-scoped-to-two-fields"})

    def test_removing_any_one_fact_makes_a_complete_profile_incomplete(self):
        for fact in profile.FACTS:
            doc = copy.deepcopy(self.docs["complete-declared"])
            doc["facts"][fact] = []
            self.assertEqual(outcomes(doc)[f"profile.{fact}"], "UNKNOWN", fact)
            self.assertIs(profile.assess_profile(doc)["complete"], False, fact)


class Equivalence(unittest.TestCase):
    def setUp(self):
        self.docs = valid()
        self.base = self.docs["complete-declared"]

    def test_a_profile_is_equivalent_to_itself(self):
        self.assertTrue(profile.equivalent(self.base, copy.deepcopy(self.base), profile.FACTS)[0])

    def test_a_sibling_product_of_the_same_vendor_is_not_equivalent_and_inherits_nothing(self):
        sibling = self.docs["sibling-product-nothing-stated"]
        self.assertEqual(sibling["identity"]["vendor"], self.base["identity"]["vendor"])
        for a, b in ((self.base, sibling), (sibling, self.base)):
            answer, reason = profile.equivalent(a, b, ["jetpack"])
            self.assertIs(answer, False, reason)
        for fact in profile.FACTS:
            self.assertEqual(profile.resolve(sibling, fact)["state"], "missing", fact)
        self.assertNotIn("PASS", outcomes(sibling).values())

    def test_another_hardware_or_software_revision_is_not_equivalent_without_a_statement(self):
        for other in ("later-software-revision", "other-revision-only"):
            for a, b in ((self.base, self.docs[other]), (self.docs[other], self.base)):
                answer, reason = profile.equivalent(a, b, ["architecture"])
                self.assertIs(answer, False, f"{other}: {reason}")

    def test_an_equivalence_statement_covers_only_the_fields_it_names_and_only_one_way(self):
        scoped = self.docs["equivalence-scoped-to-two-fields"]
        self.assertTrue(profile.equivalent(scoped, self.base, ["jetpack", "jetson_linux"])[0])
        answer, reason = profile.equivalent(scoped, self.base, ["jetpack", "cuda"])
        self.assertIs(answer, False)
        self.assertIn("cuda", reason)
        self.assertIs(profile.equivalent(self.base, scoped, ["jetpack"])[0], False)

    def test_an_equivalence_statement_names_one_exact_configuration(self):
        scoped = self.docs["equivalence-scoped-to-two-fields"]
        for key in profile.IDENTITY:
            other = copy.deepcopy(self.base)
            other["identity"][key] = "something else"
            self.assertIs(profile.equivalent(scoped, other, ["jetpack"])[0], False, key)

    def test_an_unidentified_configuration_is_equivalent_to_nothing_not_even_a_copy(self):
        vague = self.docs["missing-software-revision"]
        answer, reason = profile.equivalent(vague, copy.deepcopy(vague), ["architecture"])
        self.assertIs(answer, False)
        self.assertIn("software_revision", reason)

    def test_unknown_or_empty_field_lists_are_refused(self):
        self.assertIs(profile.equivalent(self.base, self.base, [])[0], False)
        self.assertIs(profile.equivalent(self.base, self.base, ["gpu"])[0], False)


class ExportToTheExistingTargetRecord(unittest.TestCase):
    """The only route from a profile to the CLI: the small record `--target` already reads."""

    def setUp(self):
        self.docs = valid()

    def test_every_export_is_declared_and_loads_as_a_target_record(self):
        for name, doc in self.docs.items():
            record = profile.to_target_record(doc)
            self.assertEqual(record["status"], "declared", name)
            self.assertNotIn("observed", json.dumps(record).replace("not read from a device", ""), name)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "t.json"
                path.write_text(json.dumps(record), encoding="utf-8")
                self.assertEqual(load_target(str(path)), (record, None), name)

    def test_a_complete_export_gives_the_same_report_checks_as_the_shipped_jetpack_record(self):
        shipped = json.loads((ROOT / "examples" / "targets" / "jetpack-6.2.json").read_text(encoding="utf-8"))
        exported = profile.to_target_record(self.docs["complete-declared"])
        for key in ("architecture", "software", "runtimes", "status"):
            self.assertEqual(exported[key], shipped[key], key)
        (code_a, a), (code_b, b) = report_with_target(exported), report_with_target(shipped)
        self.assertEqual(code_a, code_b)
        self.assertEqual([(c["id"], c["outcome"], c["evidence"]) for c in a["checks"]],
                         [(c["id"], c["outcome"], c["evidence"]) for c in b["checks"]])

    def test_no_export_makes_a_report_claim_hardware_or_an_observed_target(self):
        for name, doc in self.docs.items():
            _, report = report_with_target(profile.to_target_record(doc))
            self.assertEqual(validate(report, REPORT_SCHEMA), [], name)
            self.assertIs(report["hardware_verified"], False, name)
            self.assertIn("jetson.gpu", report["requires_hardware"], name)
            self.assertEqual(report["target"]["record"]["status"], "declared", name)
            for c in report["checks"]:
                if c["id"].startswith(("target.", "runtime.")):
                    self.assertNotEqual(c["evidence"], "observed", f"{name}: {c['id']}")

    def test_a_fact_the_profile_does_not_state_once_is_unknown_in_the_report_never_pass(self):
        for name, doc in self.docs.items():
            _, report = report_with_target(profile.to_target_record(doc))
            got = checks_by_id(report)
            for fact, cid in (("jetpack", "target.jetpack"), ("jetson_linux", "target.l4t"),
                              ("cuda", "runtime.cuda"), ("tensorrt", "runtime.tensorrt")):
                if profile.resolve(doc, fact)["state"] != "stated":
                    self.assertEqual(got[cid], ["UNKNOWN"], f"{name}: {cid}")
            if any(profile.resolve(doc, f)["state"] != "stated" for f in VERSIONS):
                self.assertNotEqual(report["overall"], "PASS", name)

    def test_a_mismatched_software_revision_fails_the_l4t_comparison(self):
        # The later revision declares Jetson Linux 36.x; an r35 image is a declared mismatch, not a pass.
        _, report = report_with_target(profile.to_target_record(self.docs["later-software-revision"]), tag="r35.4.1")
        self.assertEqual(checks_by_id(report)["target.l4t"], ["FAIL"])
        self.assertEqual(report["overall"], "FAIL")

    def test_the_export_cites_only_the_statements_it_used(self):
        doc = self.docs["contradictory-jetpack"]
        whats = [s["what"] for s in profile.to_target_record(doc)["sources"]]
        self.assertFalse([w for w in whats if w.startswith("jetpack:")])
        self.assertTrue([w for w in whats if w.startswith("jetson_linux:")])


class AProfileIsNotATargetRecordOrAReport(unittest.TestCase):
    def setUp(self):
        self.docs = valid()

    def test_a_profile_given_to_target_by_mistake_establishes_nothing(self):
        for name, doc in self.docs.items():
            _, report = report_with_target(doc)
            got = checks_by_id(report)
            for cid in ("target.jetpack", "target.l4t", "runtime.cuda", "runtime.tensorrt"):
                self.assertEqual(got[cid], ["UNKNOWN"], f"{name}: {cid}")
            self.assertNotIn("target.architecture", got, name)
            self.assertEqual(report["overall"], "UNKNOWN", name)
            self.assertIs(report["hardware_verified"], False, name)

    def test_the_report_reader_rejects_a_profile_even_if_relabelled(self):
        for name, doc in self.docs.items():
            self.assertTrue(contract.check_report(doc), name)
            self.assertTrue(contract.check_report(dict(doc, schema_version="1")), name)
            self.assertTrue(validate(doc, REPORT_SCHEMA), name)

    def test_the_profile_reader_rejects_reports_target_records_and_sketches(self):
        others = [*sorted((ROOT / "tests" / "fixtures" / "reports" / "valid").glob("*.json")),
                  *sorted((ROOT / "tests" / "fixtures" / "targets").glob("*.json")),
                  *sorted((ROOT / "examples").rglob("*.json"))]
        self.assertGreaterEqual(len(others), 12)
        for path in others:
            self.assertIsNone(profile.load_profile(path.read_text(encoding="utf-8"))[0], path.name)

    def test_no_cli_command_reads_a_profile(self):
        # The companion record is a library contract; the CLI surface is unchanged.
        source = (ROOT / "src" / "egrit_preflight" / "cli.py").read_text(encoding="utf-8")
        self.assertNotIn("profile", source)


if __name__ == "__main__":
    unittest.main()
