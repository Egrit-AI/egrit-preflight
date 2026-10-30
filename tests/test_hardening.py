"""Hostile or malformed input: a registry, an image, a target file, a container's output, an output path."""

import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from egrit_preflight import cli, safe
from egrit_preflight.image import inspect_image, valid_reference, version_tuple
from egrit_preflight.smoke import valid_module
from tests.fakes import DIGEST, INFO_ARM, FakeRunner, bad, docker_ok, image_inspect, inspect_rule, ok

P = f"ubuntu@{DIGEST}"


def registry(text):
    return FakeRunner([(("docker", "image", "inspect"), bad("No such image")),
                       (("docker", "buildx", "imagetools"), ok(text))])


def by_id(r, cid):
    return next(c for c in r["checks"] if c["id"] == cid)


def tmpdir():
    return Path(tempfile.mkdtemp())


def run_cli(argv, runner, env=None):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch("egrit_preflight.host.platform.system", return_value="Linux"), \
            mock.patch("egrit_preflight.host.platform.machine", return_value="aarch64"), \
            mock.patch.dict(os.environ, env or {}):
        code = cli.main(argv, out=out, err=err, runner=runner)
    return code, out.getvalue(), err.getvalue()


class MalformedRegistryAndImageOutput(unittest.TestCase):
    def test_platform_with_non_string_fields_does_not_crash(self):
        doc = {"manifests": [{"platform": {"os": 5, "architecture": "arm64"}},
                             {"platform": {"os": "linux", "architecture": ["arm64"]}},
                             {"platform": {"os": "linux", "architecture": "arm64", "variant": 7}}]}
        r = inspect_image(P, runner=registry(json.dumps(doc)))
        self.assertEqual(r["platforms"], ["linux/arm64"])

    def test_non_string_attestation_digest_does_not_crash(self):
        arm = "sha256:" + "1" * 64
        doc = {"manifests": [{"platform": {"os": "linux", "architecture": "arm64"}, "digest": arm},
                             {"digest": "sha256:" + "2" * 64,
                              "annotations": {"vnd.docker.reference.type": "attestation-manifest",
                                              "vnd.docker.reference.digest": [1]}}]}
        r = inspect_image(P, runner=registry(json.dumps(doc)))
        self.assertEqual(by_id(r, "image.sbom")["outcome"], "UNKNOWN")

    def test_deeply_nested_json_does_not_crash(self):
        for text in ("[" * 200000, '{"a":' * 100000):
            r = inspect_image(P, runner=registry(text))
            self.assertEqual(by_id(r, "image.architecture")["outcome"], "UNKNOWN")

    def test_local_inspect_with_wrong_shapes_does_not_crash(self):
        for text in ("[1]", "{}", '"x"', "[]", "null", '[{"Architecture": 5}]', '[{"Architecture": "arm64", "Config": 3}]',
                     '[{"Architecture": "arm64", "Config": {"Env": "x", "Labels": [1]}, "RepoDigests": "y"}]'):
            fake = FakeRunner([(("docker", "image", "inspect"), ok(text)),
                               (("docker", "buildx", "imagetools"), bad("offline"))])
            inspect_image(P, runner=fake)

    def test_huge_version_numbers_are_not_versions(self):
        self.assertEqual(version_tuple("9" * 5000), ())
        self.assertEqual(version_tuple("12.6.1"), (12, 6, 1))
        self.assertEqual(version_tuple("1." * 50), (1, 1, 1, 1, 1, 1))
        fake = FakeRunner([(("docker", "image", "inspect"), ok(image_inspect("arm64", ["CUDA_VERSION=" + "9" * 5000])))])
        tgt = Path(__file__).resolve().parent.parent / "examples" / "target-orin-nano-jetpack-6.2.json"
        r = inspect_image(P, str(tgt), runner=fake)
        self.assertEqual(by_id(r, "runtime.cuda")["outcome"], "UNKNOWN")

    def test_trailing_newline_is_not_a_valid_reference_or_module(self):
        self.assertFalse(valid_reference("ubuntu\n"))
        self.assertFalse(valid_reference(f"ubuntu@{DIGEST}\n"))
        self.assertFalse(valid_module("os\n"))
        self.assertFalse(valid_reference(None))
        self.assertFalse(valid_reference(5))
        self.assertTrue(valid_reference(P))


class WhatReachesTheReport(unittest.TestCase):
    def test_free_text_labels_and_odd_env_values_are_not_copied(self):
        labels = {"org.opencontainers.image.source": "https://user:tok3n@git.internal/x",
                  "org.opencontainers.image.description": "internal tool for team",
                  "org.opencontainers.image.url": "https://internal/",
                  "org.opencontainers.image.version": "1.2.3",
                  "com.nvidia.cuda.version": "12.6" + "x" * 300,
                  "x.other": "no"}
        data = [{"Architecture": "arm64", "RepoDigests": [], "Config": {
            "Env": ["CUDA_VERSION=12.6.1", "TENSORRT_VERSION=10 3 spaces", "L4T_VERSION=r36.4.0;rm -rf",
                    "NVIDIA_DRIVER_CAPABILITIES=compute,utility", "SECRET=hunter2"], "Labels": labels}}]
        fake = FakeRunner([(("docker", "image", "inspect"), ok(json.dumps(data)))])
        r = inspect_image(P, runner=fake)
        text = json.dumps(r)
        for leaked in ("tok3n", "git.internal", "internal tool", "hunter2", "SECRET", "rm -rf", "spaces"):
            self.assertNotIn(leaked, text)
        deps = r["declared_dependencies"]
        self.assertEqual(deps["env"], {"CUDA_VERSION": "12.6.1", "NVIDIA_DRIVER_CAPABILITIES": "compute,utility"})
        self.assertEqual(set(deps["labels"]), {"org.opencontainers.image.version", "com.nvidia.cuda.version"})
        self.assertLessEqual(len(deps["labels"]["com.nvidia.cuda.version"]), 100)

    def test_target_name_and_status_must_be_short_printable_strings(self):
        d = tmpdir() / "t.json"
        d.write_text(json.dumps({"name": {"a": 1}, "status": "declared\x1b[2J" + "x" * 500,
                                 "software": {"jetpack": ["6.2"], "jetson_linux": "36.4.3"}}))
        fake = FakeRunner([(("docker", "image", "inspect"), ok(image_inspect("arm64")))])
        t = inspect_image(P, str(d), runner=fake)["target"]
        self.assertIsNone(t["name"])
        self.assertNotIn("\x1b", t["status"])
        self.assertLessEqual(len(t["status"]), 40)
        self.assertIsNone(t["jetpack"])

    def test_oversized_fifo_directory_and_missing_target_are_refused(self):
        d = tmpdir()
        big = d / "big.json"
        big.write_text(" " * (safe.MAX_FILE_BYTES + 10) + "{}")
        fifo = d / "fifo.json"
        os.mkfifo(fifo)
        for path in (big, fifo, d, d / "missing.json", "/dev/zero"):
            fake = FakeRunner([(("docker", "image", "inspect"), ok(image_inspect("arm64")))])
            r = inspect_image(P, str(path), runner=fake)
            self.assertEqual(by_id(r, "target.record")["outcome"], "FAIL", str(path))

    def test_invalid_json_target_is_a_failed_record_not_a_crash(self):
        d = tmpdir() / "t.json"
        d.write_text("[" * 100000)
        r = inspect_image(P, str(d), runner=FakeRunner([(("docker", "image", "inspect"), ok(image_inspect("arm64")))]))
        self.assertEqual(by_id(r, "target.record")["outcome"], "FAIL")


class Terminal(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(safe.clean("a\x1b]0;pwn\x07\x1b[2Jb\tc\nd"), "a?]0;pwn??[2Jb\tc\nd")
        self.assertEqual(safe.clean("\x9b31m"), "?31m")

    def test_container_output_cannot_drive_the_terminal(self):
        evil = "\x1b]0;pwned\x07\x1b[2J\x1b[31mFAKE PASS\x1b[0m"
        rules = [(("docker", "run"), bad(evil, 3))] + [inspect_rule()] + docker_ok(INFO_ARM)
        code, out, err = run_cli(["smoke", "--image", P, "--yes"], FakeRunner(rules))
        self.assertEqual(code, 1)
        self.assertIn("FAKE PASS", out)
        for ch in ("\x1b", "\x07"):
            self.assertNotIn(ch, out + err)

    def test_json_output_still_escapes_control_characters(self):
        evil = "\x1b[2J"
        rules = [(("docker", "run"), bad(evil, 3))] + [inspect_rule()] + docker_ok(INFO_ARM)
        _, out, _ = run_cli(["smoke", "--image", P, "--yes", "--json"], FakeRunner(rules))
        self.assertNotIn("\x1b", out)


class ExitCodesAndOptions(unittest.TestCase):
    def test_internal_error_is_not_reported_as_a_failed_check(self):
        class Boom:
            def __call__(self, argv, timeout=30.0):
                raise RuntimeError("secret /home/bob detail")
        code, out, err = run_cli(["doctor"], Boom())
        self.assertEqual(code, 4)
        self.assertIn("internal error (RuntimeError)", err)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("/home/bob", err)

    def test_debug_env_shows_the_traceback(self):
        class Boom:
            def __call__(self, argv, timeout=30.0):
                raise RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            run_cli(["doctor"], Boom(), env={"EGRIT_PREFLIGHT_DEBUG": "1"})

    def test_ctrl_c_exits_130(self):
        class Stop:
            def __call__(self, argv, timeout=30.0):
                raise KeyboardInterrupt
        code, _, err = run_cli(["doctor"], Stop())
        self.assertEqual(code, 130)

    def test_bad_timeouts_are_usage_errors(self):
        for value in ("nan", "inf", "-inf", "-1", "0", "0.5", "abc", "99999", ""):
            with self.assertRaises(SystemExit) as e, mock.patch("sys.stderr", io.StringIO()):
                cli.main(["smoke", "--image", P, "--yes", "--timeout", value])
            self.assertEqual(e.exception.code, 2, value)

    def test_good_timeout_accepted(self):
        rules = [(("docker", "run"), ok("aarch64\n"))] + [inspect_rule()] + docker_ok(INFO_ARM)
        code, _, _ = run_cli(["smoke", "--image", P, "--yes", "--timeout", "90"], FakeRunner(rules))
        self.assertEqual(code, 0)


class ReportOutputFile(unittest.TestCase):
    def rules(self):
        return FakeRunner([(("docker", "image", "inspect"), ok(image_inspect("arm64")))] + docker_ok(INFO_ARM))

    def test_new_file_is_private(self):
        path = tmpdir() / "r.json"
        code, _, _ = run_cli(["report", "--image", P, "-o", str(path)], self.rules())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        json.loads(path.read_text())

    def test_symlink_is_refused_before_any_docker_call(self):
        d = tmpdir()
        victim = d / "victim.txt"
        victim.write_text("keep me")
        link = d / "r.json"
        os.symlink(victim, link)
        fake = self.rules()
        code, _, err = run_cli(["report", "--image", P, "-o", str(link)], fake)
        self.assertEqual(code, 2)
        self.assertIn("symbolic link", err)
        self.assertEqual(fake.calls, [])
        self.assertEqual(victim.read_text(), "keep me")

    def test_missing_directory_is_refused_before_the_run(self):
        fake = self.rules()
        code, _, err = run_cli(["report", "--image", P, "-o", "/no/such/dir/r.json"], fake)
        self.assertEqual(code, 2)
        self.assertEqual(fake.calls, [])

    def test_directory_target_is_refused(self):
        fake = self.rules()
        code, _, _ = run_cli(["report", "--image", P, "-o", str(tmpdir())], fake)
        self.assertEqual(code, 2)
        self.assertEqual(fake.calls, [])

    def test_write_private_does_not_follow_a_link_created_after_the_check(self):
        d = tmpdir()
        victim = d / "victim.txt"
        victim.write_text("keep me")
        link = d / "r.json"
        os.symlink(victim, link)
        with self.assertRaises(OSError):
            safe.write_private(str(link), "overwritten")
        self.assertEqual(victim.read_text(), "keep me")

    def test_a_write_failure_after_the_run_does_not_lose_the_result(self):
        path = tmpdir() / "r.json"
        with mock.patch("egrit_preflight.safe.write_private", side_effect=OSError("disk full")):
            code, out, err = run_cli(["report", "--image", P, "-o", str(path)], self.rules())
        self.assertEqual(code, 2)
        self.assertIn("cannot write", err)
        self.assertEqual(json.loads(out)["schema_version"], "1")


if __name__ == "__main__":
    unittest.main()
