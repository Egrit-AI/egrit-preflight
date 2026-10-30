"""Design spike evidence for docs/target-neutral-design.md: synthetic x86-64 CPU and Jetson target descriptions.

Offline and deterministic: Docker is scripted (tests/fakes.py), nothing runs on hardware, and nothing is pulled. The
tests pin down what schema version 1 does with a target that is not an ARM64 Jetson, and that no input or design
sketch here can be read as a hardware result. They change no behaviour of the tool.
"""

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from egrit_preflight import cli, contract
from tests.fakes import DIGEST, INFO_ARM, INFO_X86, FakeRunner, docker_ok, image_inspect, inspect_rule, ok
from tests.jsonschema_lite import validate

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ROOT / "tests" / "fixtures" / "targets"
SCHEMA = json.loads((ROOT / "schema" / "report.schema.json").read_text())
X86 = TARGETS / "x86-64-cpu.declared.json"
JETSON = TARGETS / "jetson.declared.json"
SKETCHES = sorted(TARGETS.glob("assessment-sketch.*.json"))
TARGET_DERIVED = ("target.", "runtime.")


def report_with_target(target, info=INFO_ARM, machine="aarch64"):
    """A full v1 report for a pinned linux/arm64 image compared with `target`, against a scripted Docker."""
    runner = FakeRunner([inspect_rule(ok(image_inspect("arm64"))), *docker_ok(info)])
    out = io.StringIO()
    with mock.patch("platform.system", return_value="Linux"), mock.patch("platform.machine", return_value=machine):
        code = cli.main(["report", "--json", "--image", f"example.com/app@{DIGEST}", "--target", str(target)],
                        out=out, err=io.StringIO(), runner=runner)
    return code, out.getvalue()


def by_id(doc):
    found = {}
    for c in doc["checks"]:
        found.setdefault(c["id"], []).append(c)
    return found


class SyntheticTargetDescriptions(unittest.TestCase):
    def test_both_descriptions_are_declared_and_claim_nothing_observed(self):
        for path in (X86, JETSON):
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "declared", path.name)
            self.assertNotIn("observed", json.dumps(record).lower(), path.name)

    def test_the_jetson_description_states_no_version_it_cannot_support(self):
        record = json.loads(JETSON.read_text(encoding="utf-8"))
        values = [*record["software"].values(), *record["runtimes"].values()]
        self.assertTrue(values and all(v == "not established" for v in values), values)


class WhatVersionOneSaysAboutThem(unittest.TestCase):
    """Today's tool, unchanged, given each description. The report stays a linux/arm64 report."""

    def assert_v1_report_makes_no_device_claim(self, text, name):
        doc, problems = contract.load_report(text)
        self.assertEqual(problems, [], name)
        self.assertEqual(validate(doc, SCHEMA), [], name)
        self.assertEqual(doc["schema_version"], "1", name)
        self.assertIs(doc["hardware_verified"], False, name)
        self.assertEqual(doc["target"]["architecture"], "linux/arm64", name)
        self.assertIn("jetson.gpu", doc["requires_hardware"], name)
        for c in doc["checks"]:
            if c["id"].startswith(TARGET_DERIVED):
                self.assertNotEqual(c["evidence"], "observed", f"{name}: {c['id']}")
        return doc

    def test_a_declared_jetson_with_no_versions_gives_unknown_never_pass(self):
        code, text = report_with_target(JETSON)
        doc = self.assert_v1_report_makes_no_device_claim(text, "jetson")
        checks = by_id(doc)
        for cid in ("target.jetpack", "target.l4t", "runtime.cuda", "runtime.tensorrt"):
            self.assertEqual([c["outcome"] for c in checks[cid]], ["UNKNOWN"], cid)
        self.assertTrue(all(c["outcome"] == "REQUIRES_HARDWARE" for c in checks["jetson.gpu"]))
        self.assertEqual(doc["overall"], "UNKNOWN")
        self.assertEqual(code, 0)

    def test_an_x86_description_does_not_turn_the_report_into_an_x86_report(self):
        for info, machine in ((INFO_ARM, "aarch64"), (INFO_X86, "x86_64")):
            code, text = report_with_target(X86, info, machine)
            doc = self.assert_v1_report_makes_no_device_claim(text, machine)
            view = contract.allowlisted_view(doc)
            self.assertEqual(view["target"]["architecture"], "linux/arm64")
            # The host may be x86-64 (doctor says so). Apart from the refusal, no check about the image or the
            # target names x86-64, and none claims anything about it.
            about_target = [c for c in view["checks"] if c["section"] != "doctor" and c["id"] != "target.architecture"]
            self.assertNotIn("x86", json.dumps(about_target).lower(), machine)
            [arch] = by_id(doc)["image.architecture"]
            self.assertIn("linux/arm64", arch["summary"])

    def test_an_x86_description_is_refused_with_a_declared_fail(self):
        code, text = report_with_target(X86)
        doc = self.assert_v1_report_makes_no_device_claim(text, "x86")
        [refusal] = by_id(doc)["target.architecture"]
        self.assertEqual((refusal["outcome"], refusal["evidence"]), ("FAIL", "declared"))
        self.assertIn("linux/arm64 only", refusal["summary"])
        self.assertEqual(doc["overall"], "FAIL")
        self.assertEqual(code, 1)

    def test_an_arm64_description_passes_as_declared_and_an_absent_one_adds_no_check(self):
        _, text = report_with_target(JETSON)
        [declared] = by_id(json.loads(text))["target.architecture"]
        self.assertEqual((declared["outcome"], declared["evidence"]), ("PASS", "declared"))
        for value in ("arm64", "AArch64", "not established", None, 64, "amd64"):
            record = json.loads(JETSON.read_text(encoding="utf-8"))
            if value is None:
                record.pop("architecture")
            else:
                record["architecture"] = value
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "target.json"
                path.write_text(json.dumps(record), encoding="utf-8")
                _, text = report_with_target(path)
            doc = self.assert_v1_report_makes_no_device_claim(text, repr(value))
            got = [c["outcome"] for c in by_id(doc).get("target.architecture", [])]
            expected = {"arm64": ["PASS"], "AArch64": ["PASS"], 64: ["FAIL"], "amd64": ["FAIL"]}.get(value, [])
            self.assertEqual(got, expected, repr(value))


class VersionOneCannotBeStretched(unittest.TestCase):
    def setUp(self):
        _, text = report_with_target(JETSON)
        self.base = json.loads(text)

    def test_the_schema_rejects_any_target_architecture_but_linux_arm64(self):
        for arch in ("linux/amd64", "linux/arm64/v8", "jetson", "any"):
            doc = copy.deepcopy(self.base)
            doc["target"]["architecture"] = arch
            self.assertTrue(validate(doc, SCHEMA), arch)

    def test_the_reference_reader_rejects_any_target_architecture_but_linux_arm64(self):
        # The reader agrees with the schema: everything the schema accepts is still accepted.
        self.assertEqual(contract.check_report(self.base), [])
        for arch in ("linux/amd64", "linux/arm64/v8", "aarch64", "", None, 64):
            doc = copy.deepcopy(self.base)
            doc["target"]["architecture"] = arch
            problems = contract.check_report(doc)
            self.assertTrue(any("target.architecture must be 'linux/arm64'" in x for x in problems), repr(arch))
            self.assertTrue(validate(doc, SCHEMA), repr(arch))
        doc = copy.deepcopy(self.base)
        doc["target"].pop("architecture")
        self.assertTrue(contract.check_report(doc))

    def test_relabelling_a_report_as_version_2_is_rejected(self):
        doc = copy.deepcopy(self.base)
        doc["schema_version"] = "2"
        self.assertTrue(contract.check_report(doc))
        self.assertEqual(contract.SUPPORTED_SCHEMA_VERSIONS, ("1",))

    def test_a_target_specific_gpu_result_cannot_be_smuggled_in(self):
        doc = copy.deepcopy(self.base)
        doc["checks"].append({"id": "x86.gpu", "section": "image", "outcome": "PASS", "evidence": "observed",
                              "summary": "Accelerator works."})
        doc["hardware_verified"] = True
        self.assertTrue(contract.check_report(doc))


class AssessmentSketches(unittest.TestCase):
    """The separate target assessment document is design only. A version 1 reader must never accept it."""

    def sketches(self):
        self.assertEqual(len(SKETCHES), 2)
        return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in SKETCHES}

    def test_the_v1_reader_rejects_every_sketch_even_if_mislabelled_as_v1(self):
        for name, doc in self.sketches().items():
            self.assertTrue(contract.check_report(doc), name)
            self.assertTrue(validate(doc, SCHEMA), name)
            relabelled = dict(doc, schema_version="1")
            self.assertTrue(contract.check_report(relabelled), name)
            self.assertTrue(validate(relabelled, SCHEMA), name)

    def test_every_sketch_is_design_only_and_claims_no_hardware(self):
        for name, doc in self.sketches().items():
            self.assertIs(doc["design_only"], True, name)
            self.assertIs(doc["hardware_verified"], False, name)
            self.assertEqual(doc["target"]["status"], "declared", name)
            self.assertNotEqual(doc["arm64_report"]["applies_to_target"], "yes", name)
            for c in doc["checks"]:
                self.assertIn(c["outcome"], contract.OUTCOMES, f"{name}: {c['id']}")
                self.assertIn(c["evidence"], contract.EVIDENCE, f"{name}: {c['id']}")
                self.assertNotEqual(c["evidence"], "observed", f"{name}: {c['id']}")
                self.assertNotEqual(c["outcome"], "PASS", f"{name}: {c['id']}")

    def test_an_accelerator_is_always_requires_hardware(self):
        doc = self.sketches()["assessment-sketch.jetson.json"]
        gpu = [c for c in doc["checks"] if c["id"].startswith("accelerator.")]
        self.assertTrue(gpu and all(c["outcome"] == "REQUIRES_HARDWARE" for c in gpu))


if __name__ == "__main__":
    unittest.main()
