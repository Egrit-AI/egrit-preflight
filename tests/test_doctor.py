import tempfile
import unittest
from pathlib import Path

from egrit_preflight import host
from egrit_preflight.doctor import run_doctor
from tests.fakes import FakeRunner, INFO_ARM, INFO_X86, bad, docker_ok, ok
from egrit_preflight.runner import CmdResult


def by_id(result, cid):
    return next(c for c in result["checks"] if c["id"] == cid)


def binfmt_file(text):
    d = tempfile.mkdtemp()
    p = Path(d) / "qemu-aarch64"
    p.write_text(text)
    return p


class Doctor(unittest.TestCase):
    def test_linux_x86_with_qemu(self):
        r = run_doctor(FakeRunner(docker_ok()), "Linux", "x86_64", binfmt_file("enabled\ninterpreter /usr/bin/q\n"))
        self.assertEqual(r["arm64_execution_mode"], "linux-x86_64-qemu")
        self.assertEqual(by_id(r, "arm64.execution")["outcome"], "PASS")
        self.assertEqual(by_id(r, "docker.buildx")["outcome"], "PASS")

    def test_linux_x86_missing_binfmt_is_fail_with_manual_recipe_and_nothing_run(self):
        fake = FakeRunner(docker_ok())
        r = run_doctor(fake, "Linux", "x86_64", Path("/nonexistent/qemu-aarch64"))
        c = by_id(r, "arm64.execution")
        self.assertEqual(c["outcome"], "FAIL")
        self.assertIn("--privileged", c["remediation"])
        self.assertFalse(any("run" in call[:2] for call in fake.calls), "doctor must never docker run")

    def test_linux_x86_disabled_binfmt(self):
        r = run_doctor(FakeRunner(docker_ok()), "Linux", "x86_64", binfmt_file("disabled\n"))
        self.assertEqual(by_id(r, "arm64.execution")["outcome"], "FAIL")

    def test_native_arm64(self):
        r = run_doctor(FakeRunner(docker_ok(INFO_ARM)), "Linux", "aarch64", Path("/nonexistent"))
        self.assertEqual(r["arm64_execution_mode"], "linux-arm64-native")
        self.assertEqual(by_id(r, "arm64.execution")["outcome"], "PASS")

    def test_apple_silicon(self):
        r = run_doctor(FakeRunner(docker_ok(INFO_ARM)), "Darwin", "arm64")
        self.assertEqual(r["arm64_execution_mode"], "macos-apple-silicon-vm")
        self.assertEqual(by_id(r, "arm64.execution")["outcome"], "PASS")

    def test_intel_mac_is_unknown_until_smoke(self):
        r = run_doctor(FakeRunner(docker_ok(INFO_X86)), "Darwin", "x86_64")
        self.assertEqual(r["arm64_execution_mode"], "macos-intel-docker-desktop-emulation")
        self.assertEqual(by_id(r, "arm64.execution")["outcome"], "UNKNOWN")

    def test_missing_docker_cli(self):
        fake = FakeRunner([(("docker",), CmdResult(["docker"], 127, "", "not found", not_found=True))])
        r = run_doctor(fake, "Linux", "x86_64")
        self.assertEqual(by_id(r, "docker.cli")["outcome"], "FAIL")
        self.assertEqual(by_id(r, "docker.daemon")["outcome"], "UNKNOWN")
        self.assertIn("docs.docker.com", by_id(r, "docker.cli")["remediation"])

    def test_daemon_not_running(self):
        rules = [(("docker", "info"), bad("Cannot connect to the Docker daemon at unix:///var/run/docker.sock"))]
        r = run_doctor(FakeRunner(rules + docker_ok()), "Linux", "x86_64", Path("/nonexistent"))
        c = by_id(r, "docker.daemon")
        self.assertEqual(c["outcome"], "FAIL")
        self.assertIn("Cannot connect", c["detail"])
        self.assertEqual(by_id(r, "arm64.execution")["outcome"], "UNKNOWN")

    def test_missing_buildx_is_unknown_not_fail(self):
        rules = [(("docker", "buildx"), bad("unknown command"))]
        r = run_doctor(FakeRunner(rules + docker_ok()), "Linux", "x86_64", binfmt_file("enabled\n"))
        self.assertEqual(by_id(r, "docker.buildx")["outcome"], "UNKNOWN")

    def test_gpu_always_requires_hardware(self):
        r = run_doctor(FakeRunner(docker_ok(INFO_ARM)), "Linux", "aarch64")
        self.assertEqual(by_id(r, "jetson.gpu")["outcome"], "REQUIRES_HARDWARE")

    def test_normalise_arch(self):
        self.assertEqual(host.normalise_arch("AMD64"), "x86_64")
        self.assertEqual(host.normalise_arch("arm64"), "arm64")
        self.assertEqual(host.normalise_arch("aarch64"), "arm64")


if __name__ == "__main__":
    unittest.main()
