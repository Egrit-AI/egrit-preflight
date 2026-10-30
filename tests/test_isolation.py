"""Container isolation and process handling: volumes, runtime, output flooding, cleanup, what image output may decide."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from egrit_preflight.runner import MAX_CAPTURE, CmdResult, run
from egrit_preflight.smoke import MAX_VOLUMES, build_run_argv, declared_volumes, run_smoke
from tests.fakes import DIGEST, FakeRunner, bad, inspect_rule, ok

PINNED = f"ubuntu@{DIGEST}"


def by_id(r, cid):
    return next(c for c in r["checks"] if c["id"] == cid)


def smoke_runner(run_result, volumes="null", extra=()):
    return FakeRunner([(("docker", "run"), run_result), (("docker", "rm"), ok()), inspect_rule(volumes=volumes), *extra])


class Runner(unittest.TestCase):
    def test_a_flooding_process_is_cut_off_and_memory_stays_small(self):
        flood = "import sys\nwhile True: sys.stdout.write('x'*100000); sys.stderr.write('y'*100000)"
        t = time.monotonic()
        r = run([sys.executable, "-c", flood], 2, limit=4096)
        self.assertTrue(r.timed_out)
        self.assertEqual(r.returncode, 124)
        self.assertLessEqual(len(r.stdout), 4096)
        self.assertLessEqual(len(r.stderr), 4096)
        self.assertTrue(r.truncated)
        self.assertLess(time.monotonic() - t, 10)

    def test_large_finite_output_is_truncated_but_the_exit_status_is_kept(self):
        r = run([sys.executable, "-c", "import sys; sys.stdout.write('z'*3000000); sys.exit(7)"], 20, limit=1000)
        self.assertEqual((r.returncode, len(r.stdout), r.truncated, r.timed_out), (7, 1000, True, False))
        self.assertTrue(r.record()["output_truncated"])

    def test_normal_output_is_not_marked_truncated(self):
        r = run([sys.executable, "-c", "print('hi'); import sys; print('err', file=sys.stderr)"], 20)
        self.assertEqual((r.stdout, r.stderr, r.returncode, r.truncated), ("hi\n", "err\n", 0, False))
        self.assertNotIn("output_truncated", r.record())
        self.assertEqual(MAX_CAPTURE, 1024 * 1024)

    def test_stdin_is_closed_so_a_command_cannot_wait_for_input(self):
        r = run([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], 10)
        self.assertEqual(r.stdout.strip(), "''")

    def test_missing_and_non_executable_commands_are_results_not_crashes(self):
        r = run(["/no/such/command-xyz"], 5)
        self.assertEqual((r.returncode, r.not_found), (127, True))
        f = Path(tempfile.mkdtemp()) / "notexec"
        f.write_text("#!/bin/sh\n")
        os.chmod(f, 0o644)
        if os.geteuid() != 0:  # root can execute anything with an interpreter line
            r = run([str(f)], 5)
            self.assertEqual(r.returncode, 126)

    def test_binary_output_is_decoded_not_fatal(self):
        r = run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff\\xfeok')"], 10)
        self.assertIn("ok", r.stdout)


class Volumes(unittest.TestCase):
    def vols(self, text, **kw):
        fake = FakeRunner([inspect_rule(volumes=text)])
        return declared_volumes(PINNED, fake), fake

    def test_none_and_empty_mean_no_volumes(self):
        for text in ("null", "{}", ""):
            (v, why), _ = self.vols(text)
            self.assertEqual((v, why), ([], None), text)

    def test_declared_paths_are_returned_sorted_and_normalised(self):
        (v, why), _ = self.vols('{"/var/cache/x/":{},"/data":{},"/data/":{}}')
        self.assertEqual((v, why), (["/data", "/var/cache/x"], None))

    def test_tmp_is_already_a_tmpfs_so_it_is_skipped(self):
        (v, _), _ = self.vols('{"/tmp":{},"/data":{}}')
        self.assertEqual(v, ["/data"])

    def test_paths_that_are_not_understood_are_refused(self):
        too_many = "{" + ",".join(f'"/v{i}":{{}}' for i in range(MAX_VOLUMES + 1)) + "}"
        for text in ('{"/a/../b":{}}', '{"relative":{}}', '{"/x;rm":{}}', '{"/":{}}', '{"/a b":{}}', '{"":{}}',
                     "[]", '"x"', "not json", too_many, '{"/\\u001b[2J":{}}', '{"/' + "a" * 300 + '":{}}'):
            (v, why), _ = self.vols(text)
            self.assertEqual((v, why), (None, "unreadable"), text[:40])

    def test_platform_flag_is_tried_first_then_dropped_for_older_docker(self):
        calls = []

        def answer(argv):
            calls.append(list(argv))
            return bad("unknown flag: --platform") if "--platform" in argv else ok('{"/data":{}}')

        fake = FakeRunner([(("docker", "image", "inspect"), answer)])
        self.assertEqual(declared_volumes(PINNED, fake), (["/data"], None))
        self.assertIn("--platform", calls[0])
        self.assertNotIn("--platform", calls[1])

    def test_run_argv_overlays_each_volume_with_a_small_tmpfs(self):
        argv = build_run_argv(PINNED, "arch", "n", volumes=["/data", "/var/cache/x"])
        pairs = [(argv[i], argv[i + 1]) for i in range(len(argv) - 1) if argv[i] == "--tmpfs"]
        self.assertEqual([p[1] for p in pairs], ["/tmp:rw,noexec,nosuid,size=16m", "/data:rw,noexec,nosuid,size=16m",
                                                 "/var/cache/x:rw,noexec,nosuid,size=16m"])
        self.assertLess(argv.index("--tmpfs"), argv.index(PINNED))

    def test_a_declared_volume_is_overlaid_in_the_real_run_call(self):
        fake = smoke_runner(ok("aarch64\n"), volumes='{"/data":{}}')
        r = run_smoke(PINNED, runner=fake, name="n")
        run_call = next(c for c in fake.calls if c[:2] == ["docker", "run"])
        self.assertIn("/data:rw,noexec,nosuid,size=16m", run_call)
        self.assertEqual(r["volumes_replaced_by_tmpfs"], ["/data"])
        self.assertEqual(by_id(r, "smoke.arch")["outcome"], "PASS")

    def test_unreadable_volumes_mean_nothing_is_run(self):
        fake = smoke_runner(ok("aarch64\n"), volumes="not json")
        r = run_smoke(PINNED, runner=fake, name="n")
        self.assertEqual(by_id(r, "smoke.volumes")["outcome"], "UNKNOWN")
        self.assertFalse(r["executed"])
        self.assertFalse(any(c[:2] == ["docker", "run"] for c in fake.calls))

    def test_missing_image_is_unknown_with_a_pull_hint_and_nothing_is_run(self):
        fake = FakeRunner([(("docker", "image", "inspect"), bad("Error: No such image: x")), (("docker", "run"), ok())])
        r = run_smoke(PINNED, runner=fake, name="n")
        c = by_id(r, "smoke.arch")
        self.assertEqual(c["outcome"], "UNKNOWN")
        self.assertIn("docker pull", c["remediation"])
        self.assertFalse(any(c_[:2] == ["docker", "run"] for c_ in fake.calls))

    def test_a_failing_inspect_for_another_reason_also_blocks_the_run(self):
        fake = FakeRunner([(("docker", "image", "inspect"), bad("permission denied")), (("docker", "run"), ok())])
        r = run_smoke(PINNED, runner=fake, name="n")
        self.assertEqual(by_id(r, "smoke.volumes")["outcome"], "UNKNOWN")
        self.assertFalse(any(c_[:2] == ["docker", "run"] for c_ in fake.calls))


class RuntimeAndGpu(unittest.TestCase):
    def test_plain_runc_and_no_visible_nvidia_devices(self):
        argv = build_run_argv(PINNED, "arch", "n")
        self.assertEqual(argv[argv.index("--runtime") + 1], "runc")
        self.assertEqual(argv[argv.index("-e") + 1], "NVIDIA_VISIBLE_DEVICES=void")
        self.assertLess(argv.index("--runtime"), argv.index(PINNED))
        joined = " ".join(argv)
        for forbidden in ("--gpus", "--device", "--runtime nvidia", "--privileged", "NVIDIA_VISIBLE_DEVICES=all"):
            self.assertNotIn(forbidden, joined)


class Cleanup(unittest.TestCase):
    def test_ctrl_c_during_the_run_removes_the_container_and_propagates(self):
        def interrupt(argv):
            raise KeyboardInterrupt

        fake = FakeRunner([(("docker", "run"), interrupt), (("docker", "rm"), ok()), inspect_rule()])
        with self.assertRaises(KeyboardInterrupt):
            run_smoke(PINNED, runner=fake, name="egrit-x")
        self.assertIn(["docker", "rm", "-f", "egrit-x"], fake.calls)

    def test_an_internal_error_during_the_run_also_removes_the_container(self):
        def explode(argv):
            raise RuntimeError("boom")

        fake = FakeRunner([(("docker", "run"), explode), (("docker", "rm"), ok()), inspect_rule()])
        with self.assertRaises(RuntimeError):
            run_smoke(PINNED, runner=fake, name="egrit-x")
        self.assertIn(["docker", "rm", "-f", "egrit-x"], fake.calls)

    def test_a_failed_removal_after_a_timeout_is_retried_and_then_reported(self):
        fake = smoke_runner(CmdResult([], 124, "", "", timed_out=True))
        fake.rules.insert(0, (("docker", "rm"), bad("Error response from daemon: busy")))
        r = run_smoke(PINNED, timeout=1, runner=fake, name="egrit-x")
        c = by_id(r, "smoke.arch")
        self.assertEqual(c["outcome"], "FAIL")
        self.assertIn("may still be running", c["summary"])
        self.assertIn("docker rm -f egrit-x", c["summary"])
        self.assertEqual(sum(1 for x in fake.calls if x[:3] == ["docker", "rm", "-f"]), 2)

    def test_no_such_container_counts_as_removed(self):
        fake = smoke_runner(CmdResult([], 124, "", "", timed_out=True))
        fake.rules.insert(0, (("docker", "rm"), bad("Error: No such container: egrit-x")))
        r = run_smoke(PINNED, timeout=1, runner=fake, name="egrit-x")
        self.assertIn("container removed", by_id(r, "smoke.arch")["summary"])


class WhatImageOutputMayDecide(unittest.TestCase):
    def test_a_successful_run_is_not_reclassified_by_words_in_its_stderr(self):
        hostile = "exec format error\nUnable to find image\nCannot connect to the Docker daemon docker.sock\nNo such file or directory"
        r = run_smoke(PINNED, runner=smoke_runner(CmdResult([], 0, "aarch64\n", hostile)), name="n")
        self.assertEqual(by_id(r, "smoke.arch")["outcome"], "PASS")

    def test_a_failed_run_is_still_classified(self):
        r = run_smoke(PINNED, runner=smoke_runner(bad("exec /bin/uname: exec format error", 255)), name="n")
        self.assertIn("doctor", by_id(r, "smoke.arch")["remediation"])

    def test_the_pass_says_the_result_comes_from_the_image(self):
        r = run_smoke(PINNED, runner=smoke_runner(ok("aarch64\n")), name="n")
        self.assertIn("image's own binaries", by_id(r, "smoke.arch")["detail"])


if __name__ == "__main__":
    unittest.main()
