import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from egrit_preflight import cli, report
from tests.jsonschema_lite import validate
from tests.fakes import DIGEST, INFO_ARM, FakeRunner, bad, docker_ok, image_inspect, inspect_rule, ok

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schema" / "report.schema.json").read_text())
PINNED = f"ubuntu@{DIGEST}"


def arm_rules(run_result=None):
    rules = [inspect_rule(ok(image_inspect("arm64", ["CUDA_VERSION=12.6.1"])))]
    if run_result:
        rules.insert(0, (("docker", "run"), run_result))
    return FakeRunner(rules + docker_ok(INFO_ARM))


def run_cli(argv, runner):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch("egrit_preflight.host.platform.system", return_value="Linux"), \
            mock.patch("egrit_preflight.host.platform.machine", return_value="aarch64"):
        code = cli.main(argv, out=out, err=err, runner=runner)
    return code, out.getvalue(), err.getvalue()


class Cli(unittest.TestCase):
    def test_doctor_json_validates_against_schema(self):
        code, out, _ = run_cli(["doctor", "--json"], FakeRunner(docker_ok(INFO_ARM)))
        self.assertEqual(code, 0)
        self.assertEqual(validate(json.loads(out), SCHEMA), [])

    def test_smoke_without_consent_refuses_and_runs_nothing(self):
        fake = arm_rules()
        code, out, err = run_cli(["smoke", "--image", PINNED], fake)
        self.assertEqual(code, 2)
        self.assertIn("--yes", err)
        self.assertEqual(fake.calls, [])

    def test_full_report_with_smoke_pass(self):
        code, out, _ = run_cli(["report", "--json", "--image", PINNED, "--smoke", "--yes"], arm_rules(ok("aarch64\n")))
        self.assertEqual(code, 0)
        rep = json.loads(out)
        self.assertEqual(validate(rep, SCHEMA), [])
        self.assertTrue(rep["provenance"]["smoke_executed"])
        self.assertEqual(rep["image"]["digest"], DIGEST)
        ids = {c["id"] for c in rep["checks"]}
        self.assertTrue({"docker.cli", "image.architecture", "smoke.arch", "jetson.gpu"} <= ids)
        self.assertIn("jetson.gpu", rep["requires_hardware"])
        self.assertEqual(rep["target"]["architecture"], "linux/arm64")
        self.assertTrue(any("uname" in c["argv"] for c in rep["commands"]))
        self.assertTrue(any("not Jetson" in x or "not a Jetson" in x for x in rep["limitations"]))

    def test_smoke_pass_never_claims_gpu_pass(self):
        _, out, _ = run_cli(["report", "--json", "--image", PINNED, "--smoke", "--yes"], arm_rules(ok("aarch64\n")))
        for c in json.loads(out)["checks"]:
            if "cuda" in c["id"] or "gpu" in c["id"] or "tensorrt" in c["id"]:
                self.assertNotEqual(c["outcome"], "PASS", c["id"])

    def test_exit_codes(self):
        code, _, _ = run_cli(["smoke", "--image", PINNED, "--yes"], arm_rules(bad("boom", 2)))
        self.assertEqual(code, 1)
        code, _, _ = run_cli(["image", "--image", "bad ref"], arm_rules())
        self.assertEqual(code, 1)
        code, _, _ = run_cli(["image", "--image", PINNED, "--strict"], arm_rules())
        self.assertEqual(code, 3, "unknown target data is UNKNOWN, and --strict turns that into exit 3")
        code, _, _ = run_cli(["image", "--image", PINNED], arm_rules())
        self.assertEqual(code, 0)

    def test_report_smoke_requires_consent(self):
        code, _, err = run_cli(["report", "--image", PINNED, "--smoke"], arm_rules())
        self.assertEqual(code, 2)

    def test_usage_error_exits_2(self):
        with self.assertRaises(SystemExit) as e, mock.patch("sys.stderr", io.StringIO()):
            cli.main(["image"])
        self.assertEqual(e.exception.code, 2)

    def test_report_is_reproducible_with_source_date_epoch(self):
        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1700000000"}):
            a = run_cli(["report", "--json", "--image", PINNED], arm_rules())[1]
            b = run_cli(["report", "--json", "--image", PINNED], arm_rules())[1]
        self.assertEqual(a, b)
        self.assertEqual(json.loads(a)["timestamp"], "2023-11-14T22:13:20Z")

    def test_report_output_file(self):
        import tempfile
        p = Path(tempfile.mkdtemp()) / "r.json"
        code, out, _ = run_cli(["report", "--image", PINNED, "-o", str(p)], arm_rules())
        self.assertEqual(validate(json.loads(p.read_text()), SCHEMA), [])
        self.assertIn("Report written", out)

    def test_module_entrypoint_runs_without_docker(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PATH="/nonexistent")
        p = subprocess.run([sys.executable, "-m", "egrit_preflight", "doctor", "--json"], capture_output=True,
                           text=True, env=env)
        self.assertEqual(p.returncode, 1)
        rep = json.loads(p.stdout)
        self.assertEqual(next(c for c in rep["checks"] if c["id"] == "docker.cli")["outcome"], "FAIL")
        self.assertEqual(validate(rep, SCHEMA), [])

    def test_python_import_cli(self):
        code, out, _ = run_cli(["report", "--json", "--image", PINNED, "--smoke", "--yes", "--test", "python-import",
                                "--module", "os.path"], arm_rules(ok("imported os.path\n")))
        self.assertEqual(code, 0)
        rep = json.loads(out)
        self.assertEqual(validate(rep, SCHEMA), [])
        self.assertEqual(next(c for c in rep["checks"] if c["id"] == "smoke.python-import")["outcome"], "PASS")

    def test_python_import_without_module_fails_and_consent_text_shows_module(self):
        code, _, _ = run_cli(["smoke", "--image", PINNED, "--test", "python-import", "--yes"], arm_rules())
        self.assertEqual(code, 1)
        code, _, err = run_cli(["smoke", "--image", PINNED, "--test", "python-import", "--module", "numpy"], arm_rules())
        self.assertEqual(code, 2)
        self.assertIn("numpy", err)
        code, _, err = run_cli(["smoke", "--image", PINNED, "--test", "python-import"], arm_rules())
        self.assertEqual(code, 2, "no traceback when the module is missing and consent not given")

    def test_report_carries_provenance_and_validates(self):
        from tests.test_image import ARM, ATT_ARM, SPDX, SLSA, att, att_doc, plat, registry
        index = {"manifests": [plat(ARM, "arm64"), att(ATT_ARM, ARM)]}
        code, out, _ = run_cli(["report", "--json", "--image", PINNED], registry(index, {ATT_ARM: att_doc(SPDX, SLSA)}))
        rep = json.loads(out)
        self.assertEqual(validate(rep, SCHEMA), [])
        self.assertEqual(rep["image"]["provenance"]["status"], "listed")
        self.assertIs(rep["image"]["provenance"]["signature_verified"], False)
        ids = {c["id"]: c["outcome"] for c in rep["checks"]}
        self.assertEqual((ids["image.sbom"], ids["image.provenance"]), ("PASS", "PASS"))

    def test_schema_rejects_a_claimed_signature_verification(self):
        bad_doc = {"signature_verified": True, "status": "listed", "attestations": []}
        errs = validate(bad_doc, SCHEMA["properties"]["image"]["properties"]["provenance"])
        self.assertTrue(errs)

    def test_report_never_contains_raw_docker_info(self):
        info = json.dumps({"ServerVersion": "27.0.1", "Architecture": "aarch64", "OSType": "linux",
                           "Name": "my-private-host", "HttpProxy": "http://user:hunter2@proxy.internal:3128",
                           "NoProxy": "internal.example", "DockerRootDir": "/srv/secret-root",
                           "RegistryConfig": {"Mirrors": ["https://mirror.internal/"]}})
        code, out, _ = run_cli(["report", "--json"], FakeRunner(docker_ok(info)))
        for leaked in ("my-private-host", "hunter2", "proxy.internal", "internal.example", "secret-root",
                       "mirror.internal"):
            self.assertNotIn(leaked, out)
        rep = json.loads(out)
        cmd = next(c["command"] for c in rep["checks"] if c["id"] == "docker.daemon")
        self.assertEqual(cmd["argv"][:2], ["docker", "info"])
        self.assertNotIn("stdout", cmd)
        self.assertNotIn("stderr", cmd)
        self.assertTrue(cmd["output_omitted"])
        self.assertEqual(rep["docker"]["daemon_version"], "27.0.1", "parsed fields are still reported")

    def test_failed_docker_info_stderr_not_in_command_record(self):
        rules = [(("docker", "info"), bad("permission denied for user bob at /home/bob/.docker"))] + docker_ok()
        code, out, _ = run_cli(["doctor", "--json"], FakeRunner(rules))
        cmd = next(c["command"] for c in json.loads(out)["checks"] if c["id"] == "docker.daemon")
        self.assertNotIn("stderr", cmd)

    def test_version(self):
        with self.assertRaises(SystemExit) as e, mock.patch("sys.stdout", io.StringIO()):
            cli.main(["--version"])
        self.assertEqual(e.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
