"""The report contract: fixtures, schema, invariants, the consumer allowlist, and bounded reading."""

import copy
import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from egrit_preflight import cli, contract
from egrit_preflight.runner import CmdResult
from tests import make_fixtures
from tests.fakes import DIGEST, INFO_ARM, INFO_X86, FakeRunner, bad, docker_ok, image_inspect, inspect_rule, ok
from tests.jsonschema_lite import validate

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "reports"
SCHEMA = json.loads((ROOT / "schema" / "report.schema.json").read_text())
REGENERATE = "Run `python3 -m tests.make_fixtures` and review the diff: the report changed, so the contract did."

# Rejections JSON Schema alone cannot express: the schema accepts these, check_report must not.
BEYOND_SCHEMA = {"gpu-check-pass.json", "gpu-check-observed.json", "checks-empty.json", "gpu-check-missing.json",
                 "requires-hardware-without-gpu.json", "requires-hardware-emptied.json", "overall-pass-over-a-fail.json",
                 "declared-claimed-observed.json", "sbom-claimed-observed.json",
                 "uncertainty-outcome-verified.json", "uncertainties-emptied.json", "architecture-control-chars.json"}


def valid():
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted((FIXTURES / "valid").glob("*.json"))}


def invalid():
    return {p.name: p.read_text(encoding="utf-8") for p in sorted((FIXTURES / "invalid").glob("*.json"))}


class Fixtures(unittest.TestCase):
    def test_every_valid_fixture_is_accepted(self):
        self.assertGreaterEqual(len(valid()), 6)
        for name, text in valid().items():
            doc, problems = contract.load_report(text)
            self.assertEqual(problems, [], name)
            self.assertEqual(validate(doc, SCHEMA), [], name)

    def test_the_fixtures_cover_the_cases_a_consumer_must_handle(self):
        docs = {n: json.loads(t) for n, t in valid().items()}
        outcomes = {c["outcome"] for d in docs.values() for c in d["checks"]}
        self.assertEqual(outcomes, set(contract.OUTCOMES))
        evidence = {c["evidence"] for d in docs.values() for c in d["checks"]}
        self.assertTrue({"observed", "declared"} <= evidence)
        self.assertTrue(any(d["image"] is None for d in docs.values()), "a report with no image")
        self.assertTrue(any(d["image"] and d["image"]["digest"] for d in docs.values()), "an immutable digest")
        self.assertTrue(any(d["image"] and d["image"]["digest"] is None for d in docs.values()), "a mutable tag")
        self.assertTrue(any(d["target"]["record"] is None for d in docs.values()), "a missing target")
        self.assertTrue(any(d["target"]["record"] for d in docs.values()), "a target record")
        self.assertTrue(any(d["overall"] == "PASS" and d["requires_hardware"] for d in docs.values()),
                        "PASS with hardware still required")
        self.assertTrue(any(d["overall"] == "FAIL" for d in docs.values()))
        self.assertTrue(all(d["hardware_verified"] is False for d in docs.values()))

    def test_every_invalid_fixture_is_rejected_for_the_reason_it_was_made(self):
        expected = {name: phrase for name, (_, phrase) in make_fixtures.invalid_fixtures().items()}
        self.assertEqual(set(invalid()), set(expected), "an invalid fixture has no expectation, or the reverse")
        for name, text in invalid().items():
            doc, problems = contract.load_report(text)
            self.assertIsNone(doc, name)
            self.assertTrue(any(expected[name] in p for p in problems), f"{name}: {problems}")

    def test_the_schema_agrees_with_check_report_where_it_can(self):
        for name, text in invalid().items():
            try:
                doc = json.loads(text)
            except ValueError:
                continue
            schema_problems = validate(doc, SCHEMA)
            if name in BEYOND_SCHEMA:
                self.assertEqual(schema_problems, [], f"{name} is meant to need the extra rules")
            elif isinstance(doc, dict):
                self.assertTrue(schema_problems, f"{name} should fail the schema as well")

    def test_committed_fixtures_are_current(self):
        fresh = make_fixtures.valid_fixtures()
        self.assertEqual({n: fresh[n] for n in fresh}, valid(), REGENERATE)
        self.assertEqual({n: t for n, (t, _) in make_fixtures.invalid_fixtures(fresh).items()}, invalid(), REGENERATE)

    def test_the_example_report_in_the_docs_satisfies_the_contract(self):
        doc, problems = contract.load_report((ROOT / "docs" / "example-report.json").read_bytes())
        self.assertEqual(problems, [])
        self.assertEqual(validate(doc, SCHEMA), [])


class WhatTheToolCanProduce(unittest.TestCase):
    """Whatever state the machine is in, the report must satisfy the contract."""

    def run_report(self, argv, runner, system="Linux", machine="aarch64"):
        out = io.StringIO()
        with mock.patch("platform.system", return_value=system), mock.patch("platform.machine", return_value=machine):
            code = cli.main(argv, out=out, err=io.StringIO(), runner=runner)
        return code, out.getvalue()

    def test_a_broad_set_of_situations_all_produce_acceptable_reports(self):
        ref = f"example.com/app@{DIGEST}"
        timed_out = CmdResult([], 124, "", "", timed_out=True)
        situations = {
            "docker missing": (["report", "--json", "--image", ref], FakeRunner([(("docker",), CmdResult([], 127, "", "x", not_found=True))])),
            "daemon down": (["report", "--json"], FakeRunner([(("docker", "info"), bad("Cannot connect")), *docker_ok()])),
            "registry down": (["report", "--json", "--image", ref], FakeRunner(docker_ok(INFO_ARM))),
            "wrong architecture": (["report", "--json", "--image", ref], FakeRunner([inspect_rule(ok(image_inspect("amd64"))), *docker_ok(INFO_ARM)])),
            "invalid reference": (["report", "--json", "--image", "bad ref"], FakeRunner(docker_ok(INFO_ARM))),
            "unreadable target": (["report", "--json", "--image", ref, "--target", "/no/such/file"], FakeRunner([inspect_rule(ok(image_inspect("arm64"))), *docker_ok(INFO_ARM)])),
            "smoke timeout": (["report", "--json", "--image", ref, "--smoke", "--yes"], FakeRunner([(("docker", "run"), timed_out), (("docker", "rm"), ok()), inspect_rule(ok(image_inspect("arm64"))), *docker_ok(INFO_ARM)])),
            "smoke wrong output": (["report", "--json", "--image", ref, "--smoke", "--yes"], FakeRunner([(("docker", "run"), ok("x86_64\n")), inspect_rule(ok(image_inspect("arm64"))), *docker_ok(INFO_ARM)])),
            "smoke exec format": (["report", "--json", "--image", ref, "--smoke", "--yes"], FakeRunner([(("docker", "run"), bad("exec format error", 255)), inspect_rule(ok(image_inspect("arm64"))), *docker_ok(INFO_ARM)])),
            "unreadable volumes": (["report", "--json", "--image", ref, "--smoke", "--yes"], FakeRunner([inspect_rule(ok(image_inspect("arm64")), volumes="not json"), *docker_ok(INFO_ARM)])),
            "mutable tag refused": (["report", "--json", "--image", "ubuntu:24.04", "--smoke", "--yes"], FakeRunner([inspect_rule(ok(image_inspect("arm64"))), *docker_ok(INFO_ARM)])),
        }
        for name, (argv, runner) in situations.items():
            code, text = self.run_report(argv, runner)
            doc, problems = contract.load_report(text)
            self.assertEqual(problems, [], f"{name}: {problems}")
            self.assertEqual(validate(doc, SCHEMA), [], name)
            self.assertIs(doc["hardware_verified"], False, name)
        code, text = self.run_report(["report", "--json"], FakeRunner(docker_ok(INFO_X86)), "Linux", "x86_64")
        self.assertEqual(contract.load_report(text)[1], [])

    def test_a_clean_doctor_run_says_pass_and_still_says_no_hardware_was_verified(self):
        code, text = self.run_report(["report", "--json"], FakeRunner(docker_ok(INFO_ARM)))
        doc = json.loads(text)
        self.assertEqual(doc["overall"], "PASS")
        self.assertEqual(doc["requires_hardware"], ["jetson.gpu"])
        self.assertIs(doc["hardware_verified"], False)
        self.assertEqual(code, 0)


class CannotBeMadeToLookLikeADevicePass(unittest.TestCase):
    def setUp(self):
        self.base = json.loads(valid()["pass-observed"])

    def rejected(self, mutate):
        doc = copy.deepcopy(self.base)
        mutate(doc)
        return contract.check_report(doc)

    def test_each_way_of_turning_this_into_a_device_pass_is_caught(self):
        def gpu(doc, value):
            next(c for c in doc["checks"] if c["id"] == "jetson.gpu")["outcome"] = value
        mutations = {
            "hardware_verified true": lambda d: d.update(hardware_verified=True),
            "hardware_verified removed": lambda d: d.pop("hardware_verified"),
            "hardware_verified truthy string": lambda d: d.update(hardware_verified="true"),
            "hardware_verified 1": lambda d: d.update(hardware_verified=1),
            "gpu check PASS": lambda d: gpu(d, "PASS"),
            "gpu check UNKNOWN": lambda d: gpu(d, "UNKNOWN"),
            "gpu check FAIL": lambda d: gpu(d, "FAIL"),
            "gpu check removed from requires_hardware": lambda d: d.update(requires_hardware=[]),
            "overall changed": lambda d: d.update(overall="PASS"),
            "signature verified": lambda d: d["image"]["provenance"].update(signature_verified=True),
            "signature verified as string": lambda d: d["image"]["provenance"].update(signature_verified="yes"),
        }
        for name, mutate in mutations.items():
            self.assertTrue(self.rejected(mutate), f"not caught: {name}")

    def test_the_untouched_fixture_is_accepted(self):
        self.assertEqual(contract.check_report(self.base), [])

    def test_a_new_outcome_or_grade_is_not_silently_accepted(self):
        def add_outcome(doc):
            doc["checks"][0]["outcome"] = "VERIFIED"

        def add_grade(doc):
            doc["checks"][0]["evidence"] = "hardware-measured"
        self.assertTrue(self.rejected(add_outcome))
        self.assertTrue(self.rejected(add_grade))

    def test_unknown_extra_fields_are_ignored_not_rejected(self):
        doc = copy.deepcopy(self.base)
        doc["a_future_field"] = {"x": 1}
        doc["checks"][0]["another_future_field"] = [1]
        self.assertEqual(contract.check_report(doc), [])

    def test_an_unknown_check_id_is_accepted_and_keeps_its_outcome(self):
        doc = copy.deepcopy(self.base)
        extra = dict(doc["checks"][0], id="future.new-check", outcome="UNKNOWN")
        doc["checks"].append(extra)
        doc["overall"] = "UNKNOWN"
        # as the writer does, the UNKNOWN check is also listed in uncertainties (rule 10)
        doc["uncertainties"].append({k: extra[k] for k in ("id", "section", "outcome", "summary")})
        self.assertEqual(contract.check_report(doc), [])


class ConsumerAllowlist(unittest.TestCase):
    FREE_TEXT = ("detail", "command", "commands", "limitations", "declared_dependencies", "remediation", "errors",
                 "arm64_manifest_digests")

    def walk_keys(self, value, found):
        if isinstance(value, dict):
            for k, v in value.items():
                found.add(k)
                self.walk_keys(v, found)
        elif isinstance(value, list):
            for v in value:
                self.walk_keys(v, found)
        return found

    def test_the_view_carries_what_the_importer_needs(self):
        view = contract.allowlisted_view(json.loads(valid()["pass-observed"]))
        self.assertEqual(view["schema_version"], "1")
        self.assertEqual(view["tool"], {"name": "egrit-preflight", "version": "0.1.0"})
        self.assertIn("timestamp", view)
        self.assertEqual(view["image"]["digest"], "sha256:" + "a" * 64)
        self.assertEqual(view["host"]["execution_mode"], "linux-arm64-native")
        check = view["checks"][0]
        self.assertEqual(set(check), {"id", "section", "outcome", "evidence", "summary"})
        self.assertEqual(set(view["uncertainties"][0]), {"id", "section", "outcome", "summary"})
        self.assertIs(view["hardware_verified"], False)

    def test_the_view_leaves_out_every_free_text_channel(self):
        for name, text in valid().items():
            keys = self.walk_keys(contract.allowlisted_view(json.loads(text)), set())
            self.assertFalse(keys & set(self.FREE_TEXT), f"{name}: {keys & set(self.FREE_TEXT)}")
            record = contract.allowlisted_view(json.loads(text))["target"].get("record")
            self.assertTrue(record is None or set(record) <= {"jetpack", "jetson_linux", "status"},
                            f"{name}: the target record's free-text name must not be imported")

    def test_secrets_in_every_free_text_channel_stay_out_of_the_view(self):
        sentinel = "SENTINEL-5f3a9c"
        labels = {"com.nvidia.cuda.version": "12.6", "org.opencontainers.image.version": "1"}
        data = [{"Architecture": "arm64", "RepoDigests": [], "Config": {
            "Env": [f"CUDA_VERSION=12.6.1", f"API_KEY={sentinel}"], "Labels": {**labels, "org.opencontainers.image.source": f"https://u:{sentinel}@h"}}}]
        info = json.dumps({"ServerVersion": "27.0.1", "Architecture": "aarch64", "OSType": "linux", "Name": sentinel,
                           "HttpProxy": f"http://u:{sentinel}@p"})
        rules = [(("docker", "run"), bad(f"stderr {sentinel}", 3)), inspect_rule(ok(json.dumps(data))), *docker_ok(info)]
        out = io.StringIO()
        with mock.patch("platform.system", return_value="Linux"), mock.patch("platform.machine", return_value="aarch64"):
            cli.main(["report", "--json", "--image", f"example.com/app@{DIGEST}", "--smoke", "--yes"], out=out,
                     err=io.StringIO(), runner=FakeRunner(rules))
        doc = json.loads(out.getvalue())
        self.assertNotIn(sentinel, out.getvalue().replace(f"stderr {sentinel}", ""), "outside the smoke output")
        self.assertNotIn(sentinel, json.dumps(contract.allowlisted_view(doc)))

    def test_an_invalid_report_yields_no_view(self):
        with self.assertRaises(contract.Rejected):
            contract.allowlisted_view(json.loads(invalid()["hardware-verified-true.json"]))


class BoundedReading(unittest.TestCase):
    def test_oversized_nested_binary_and_non_standard_input_is_rejected(self):
        good = valid()["pass-observed"]
        cases = {
            "oversized": " " * contract.MAX_REPORT_BYTES + good,
            "deeply nested": "[" * 200000,
            "invalid utf-8": b"\xff\xfe{}",
            "NaN": '{"x": NaN}',
            "Infinity": '{"x": Infinity}',
            "empty": "",
            "trailing garbage": good + "}",
        }
        for name, data in cases.items():
            doc, problems = contract.load_report(data)
            self.assertIsNone(doc, name)
            self.assertTrue(problems, name)

    def test_bytes_and_text_are_both_accepted(self):
        text = valid()["doctor-only"]
        self.assertIsNotNone(contract.load_report(text)[0])
        self.assertIsNotNone(contract.load_report(text.encode())[0])

    def test_text_with_a_lone_surrogate_is_rejected_not_raised(self):
        for text in ("\ud800", '{"a": "\ud800"}', valid()["doctor-only"] + "\udfff"):
            doc, problems = contract.load_report(text)
            self.assertIsNone(doc)
            self.assertEqual(problems, ["report is not valid UTF-8 text"])

    def test_nothing_is_partly_accepted(self):
        doc, problems = contract.load_report(invalid()["bad-outcome.json"])
        self.assertIsNone(doc)
        self.assertTrue(problems)

    def test_the_supported_versions_are_exactly_the_one_in_the_schema(self):
        self.assertEqual(contract.SUPPORTED_SCHEMA_VERSIONS, (SCHEMA["properties"]["schema_version"]["const"],))


if __name__ == "__main__":
    unittest.main()
