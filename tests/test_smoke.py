import unittest

from egrit_preflight.runner import CmdResult
from egrit_preflight.smoke import build_run_argv, run_smoke
from tests.fakes import DIGEST, FakeRunner, bad, inspect_rule, ok

PINNED = f"ubuntu@{DIGEST}"


def by_id(r, cid):
    return next(c for c in r["checks"] if c["id"] == cid)


def runner(run_result):
    return FakeRunner([(("docker", "run"), run_result), (("docker", "rm"), ok()),
                       (("docker", "pull"), ok()), inspect_rule()])


class Smoke(unittest.TestCase):
    def test_pass(self):
        r = run_smoke(PINNED, runner=runner(ok("aarch64\n")), name="n")
        self.assertEqual(by_id(r, "smoke.arch")["outcome"], "PASS")
        self.assertEqual(by_id(r, "jetson.gpu")["outcome"], "REQUIRES_HARDWARE")
        self.assertTrue(r["executed"])

    def test_wrong_output_fails(self):
        r = run_smoke(PINNED, runner=runner(ok("x86_64\n")), name="n")
        self.assertEqual(by_id(r, "smoke.arch")["outcome"], "FAIL")

    def test_incorrect_exit_status_fails(self):
        r = run_smoke(PINNED, runner=runner(bad("boom", 3)), name="n")
        c = by_id(r, "smoke.arch")
        self.assertEqual(c["outcome"], "FAIL")
        self.assertIn("status 3", c["summary"])

    def test_timeout_fails_and_removes_container(self):
        fake = runner(CmdResult([], 124, "", "", timed_out=True))
        r = run_smoke(PINNED, timeout=1, runner=fake, name="egrit-x")
        self.assertEqual(by_id(r, "smoke.arch")["outcome"], "FAIL")
        self.assertIn("Timed out", by_id(r, "smoke.arch")["summary"])
        self.assertIn(["docker", "rm", "-f", "egrit-x"], fake.calls)

    def test_exec_format_error_points_to_doctor(self):
        r = run_smoke(PINNED, runner=runner(bad("exec /usr/bin/uname: exec format error", 255)), name="n")
        c = by_id(r, "smoke.arch")
        self.assertEqual(c["outcome"], "FAIL")
        self.assertIn("doctor", c["remediation"])

    def test_no_docker_daemon(self):
        r = run_smoke(PINNED, runner=runner(bad("Cannot connect to the Docker daemon at unix:///x", 1)), name="n")
        c = by_id(r, "smoke.arch")
        self.assertEqual(c["outcome"], "FAIL")
        self.assertIn("doctor", c["remediation"])

    def test_missing_image_is_unknown_not_run(self):
        r = run_smoke(PINNED, runner=runner(bad("Unable to find image 'x' locally", 125)), name="n")
        self.assertEqual(by_id(r, "smoke.arch")["outcome"], "UNKNOWN")

    def test_mutable_tag_refused_unless_allowed(self):
        fake = runner(ok("aarch64\n"))
        r = run_smoke("ubuntu:24.04", runner=fake)
        self.assertEqual(by_id(r, "reference.pinned")["outcome"], "FAIL")
        self.assertFalse(r["executed"])
        self.assertEqual(fake.calls, [])
        r = run_smoke("ubuntu:24.04", allow_mutable=True, runner=runner(ok("aarch64\n")), name="n")
        self.assertEqual(by_id(r, "smoke.arch")["outcome"], "PASS")
        self.assertEqual(r["digest"], DIGEST, "digest is recorded after the run")

    def test_invalid_reference_and_unknown_test(self):
        fake = runner(ok())
        self.assertEqual(run_smoke("--privileged", runner=fake)["checks"][0]["outcome"], "FAIL")
        self.assertEqual(run_smoke(PINNED, test="rm-rf", runner=fake)["checks"][0]["outcome"], "FAIL")
        self.assertEqual(fake.calls, [])

    def test_pull_only_when_asked(self):
        fake = runner(ok("aarch64\n"))
        run_smoke(PINNED, runner=fake, name="n")
        self.assertFalse(any(c[:2] == ["docker", "pull"] for c in fake.calls))
        fake = runner(ok("aarch64\n"))
        run_smoke(PINNED, pull=True, runner=fake, name="n")
        self.assertIn(["docker", "pull", "--platform", "linux/arm64", PINNED], fake.calls)

    def test_run_argv_is_locked_down(self):
        argv = build_run_argv(PINNED, "arch", "n")
        joined = " ".join(argv)
        for needed in ("--platform linux/arm64", "--pull never", "--network none", "--read-only", "--cap-drop ALL",
                       "no-new-privileges", "--memory 512m", "--cpus 1", "--pids-limit", "--user 65534:65534",
                       "--entrypoint uname"):
            self.assertIn(needed, joined)
        for forbidden in ("--privileged", "--device", "-v ", "--volume", "--mount", "--gpus", "--runtime nvidia",
                          "--network host", "--pid host", "--pid=", "--ipc", "--cap-add"):
            self.assertNotIn(forbidden, joined)
        self.assertEqual(argv[-2:], [PINNED, "-m"])


class PythonImport(unittest.TestCase):
    def test_pass_names_module_and_not_gpu(self):
        r = run_smoke(PINNED, "python-import", module="numpy", runner=runner(ok("imported numpy\n")), name="n")
        c = by_id(r, "smoke.python-import")
        self.assertEqual(c["outcome"], "PASS")
        self.assertIn("numpy", c["summary"])
        for word in ("CUDA", "TensorRT", "GPU", "Jetson"):
            self.assertNotIn(word, c["summary"])
        self.assertEqual(by_id(r, "jetson.gpu")["outcome"], "REQUIRES_HARDWARE")
        self.assertEqual(r["module"], "numpy")

    def test_import_error_fails_with_stderr_tail(self):
        err = ("Traceback (most recent call last):\n  File \"<string>\", line 1, in <module>\n"
               "    import importlib,sys; importlib.import_module(sys.argv[1])\n"
               "                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n"
               "ModuleNotFoundError: No module named 'torch'\n")
        r = run_smoke(PINNED, "python-import", module="torch", runner=runner(bad(err, 1)), name="n")
        c = by_id(r, "smoke.python-import")
        self.assertEqual(c["outcome"], "FAIL")
        self.assertIn("No module named 'torch'", c["detail"])
        self.assertNotIn("^^^^", c["detail"])

    def test_missing_python_fails(self):
        err = 'docker: Error response: exec: "python3": executable file not found in $PATH'
        r = run_smoke(PINNED, "python-import", module="os", runner=runner(bad(err, 127)), name="n")
        c = by_id(r, "smoke.python-import")
        self.assertEqual(c["outcome"], "FAIL")
        self.assertIn("python3", c["summary"])

    def test_unexpected_output_fails(self):
        r = run_smoke(PINNED, "python-import", module="os", runner=runner(ok("imported something_else\n")), name="n")
        self.assertEqual(by_id(r, "smoke.python-import")["outcome"], "FAIL")

    def test_invalid_module_names_rejected_before_any_docker_call(self):
        for bad_name in (None, "", "os; rm -rf /", "-c", "a..b", ".os", "os.", "1abc", "a b", "x" * 101, "os\nimport"):
            fake = runner(ok("imported x\n"))
            r = run_smoke(PINNED, "python-import", module=bad_name, runner=fake, name="n")
            self.assertEqual(by_id(r, "smoke.module")["outcome"], "FAIL", repr(bad_name))
            self.assertEqual(fake.calls, [], repr(bad_name))
            self.assertFalse(r["executed"])

    def test_valid_dotted_names_accepted(self):
        for good in ("os", "os.path", "_private", "a1.b_2.c3"):
            r = run_smoke(PINNED, "python-import", module=good, runner=runner(ok(f"imported {good}\n")), name="n")
            self.assertEqual(by_id(r, "smoke.python-import")["outcome"], "PASS", good)

    def test_module_is_an_argument_never_spliced_into_code(self):
        argv = build_run_argv(PINNED, "python-import", "n", "numpy")
        self.assertEqual(argv[argv.index("--entrypoint") + 1], "python3")
        tail = argv[argv.index(PINNED) + 1:]
        self.assertEqual(tail[:3], ["-I", "-B", "-c"])
        self.assertNotIn("numpy", tail[3])
        self.assertEqual(tail[4], "numpy")

    def test_still_locked_down(self):
        joined = " ".join(build_run_argv(PINNED, "python-import", "n", "numpy"))
        for needed in ("--network none", "--read-only", "--cap-drop ALL", "--pull never", "--user 65534:65534"):
            self.assertIn(needed, joined)
        for forbidden in ("--privileged", "--device", "--gpus", "-v ", "--volume", "--mount", "--cap-add"):
            self.assertNotIn(forbidden, joined)


if __name__ == "__main__":
    unittest.main()
