"""doctor: can this machine run linux/arm64 containers, and if not, what should the developer do?"""

import re

from . import host as hostmod
from . import outcomes as o
from .runner import run as default_run

DOCKER_INSTALL = "Install Docker Engine (Linux) or Docker Desktop (macOS): https://docs.docker.com/get-docker/"
DAEMON_HELP = (
    "Start the Docker daemon (Linux: 'sudo systemctl start docker'; macOS: open Docker Desktop). "
    "If the error mentions permission denied, add your user to the 'docker' group or use rootless Docker."
)


def run_doctor(runner=default_run, system=None, machine=None, binfmt_path=hostmod.BINFMT_AARCH64):
    host = hostmod.detect_host(system, machine)
    checks = []
    docker = {"cli_version": None, "daemon_version": None, "buildx_version": None,
              "daemon_architecture": None, "daemon_os": None, "docker_desktop": None}

    r = runner(["docker", "--version"], 10)
    if r.not_found or r.returncode != 0:
        checks.append(o.check("docker.cli", o.FAIL, "Docker CLI not found.", remediation=DOCKER_INSTALL,
                              command=r.record()))
        cli_ok = False
    else:
        m = re.search(r"version ([^\s,]+)", r.stdout)
        docker["cli_version"] = m.group(1) if m else hostmod.first_line(r.stdout)
        checks.append(o.check("docker.cli", o.PASS, f"Docker CLI {docker['cli_version']}.", evidence=o.OBSERVED,
                              command=r.record()))
        cli_ok = True

    info = None
    if cli_ok:
        r = runner(["docker", "info", "--format", "{{json .}}"], 20)
        info = hostmod.parse_docker_info(r.stdout) if r.returncode == 0 else None
        if info is None:
            detail = hostmod.first_line(r.stderr) or "no output from 'docker info'"
            checks.append(o.check("docker.daemon", o.FAIL, "Docker daemon is not reachable.", detail=detail,
                                  remediation=DAEMON_HELP, command=r.record(output=False)))
        else:
            docker["daemon_version"] = info.get("ServerVersion")
            docker["daemon_architecture"] = hostmod.normalise_arch(info.get("Architecture"))
            docker["daemon_os"] = info.get("OSType")
            docker["docker_desktop"] = "docker desktop" in str(info.get("OperatingSystem", "")).lower()
            checks.append(o.check("docker.daemon", o.PASS, f"Docker daemon {docker['daemon_version']} reachable.",
                                  evidence=o.OBSERVED, command=r.record(output=False)))
    else:
        checks.append(o.check("docker.daemon", o.UNKNOWN, "Not checked: no Docker CLI."))

    if cli_ok:
        r = runner(["docker", "buildx", "version"], 10)
        if r.returncode == 0:
            m = re.search(r"v?(\d+\.\d+\.\d+[^\s]*)", r.stdout)
            docker["buildx_version"] = m.group(1) if m else hostmod.first_line(r.stdout)
            checks.append(o.check("docker.buildx", o.PASS, f"Docker Buildx {docker['buildx_version']}.",
                                  evidence=o.OBSERVED, command=r.record()))
        else:
            checks.append(o.check(
                "docker.buildx", o.UNKNOWN,
                "Docker Buildx not found. It is needed to inspect registry manifests; local smoke tests do not need it.",
                remediation="Install the docker-buildx plugin: https://docs.docker.com/build/install-buildx/",
                command=r.record()))
    else:
        checks.append(o.check("docker.buildx", o.UNKNOWN, "Not checked: no Docker CLI."))

    binfmt = hostmod.binfmt_status(binfmt_path) if host["os"] == "linux" else None
    mode = hostmod.execution_mode(host, docker["daemon_architecture"], binfmt)
    checks.append(_arm64_check(mode, host, docker, binfmt, info is not None))
    checks.append(o.check(
        "jetson.gpu", o.REQUIRES_HARDWARE,
        "CUDA, TensorRT, the NVIDIA driver and Jetson device nodes cannot be tested here.",
        detail="ARM64 user-space emulation does not emulate a Jetson GPU. Use a physical Jetson for these checks."))

    return {"host": host, "docker": docker, "arm64_execution_mode": mode, "binfmt_qemu_aarch64": binfmt,
            "checks": checks}


def _arm64_check(mode, host, docker, binfmt, daemon_ok):
    cid = "arm64.execution"
    if not daemon_ok:
        return o.check(cid, o.UNKNOWN, "ARM64 execution not assessed: Docker daemon unavailable.",
                       detail=f"mode: {mode}")
    if mode == "linux-arm64-native":
        return o.check(cid, o.PASS, "Native ARM64 Linux: containers run linux/arm64 without emulation.",
                       evidence=o.OBSERVED, detail=f"mode: {mode}")
    if mode == "macos-apple-silicon-vm":
        return o.check(cid, o.PASS,
                       "Apple Silicon: linux/arm64 containers run in Docker's Linux VM, without x86 emulation.",
                       evidence=o.OBSERVED if docker["daemon_architecture"] == "arm64" else o.DECLARED,
                       detail=f"mode: {mode}")
    if mode == "macos-intel-docker-desktop-emulation":
        return o.check(cid, o.UNKNOWN,
                       "Intel Mac: Docker Desktop emulates linux/arm64 (QEMU), slowly, if enabled. Only a smoke test shows it works.",
                       detail=f"mode: {mode}", remediation="Run: egrit-preflight smoke --image <ref> --yes")
    if mode == "linux-x86_64-qemu":
        if binfmt == "enabled":
            return o.check(cid, o.PASS,
                           "x86_64 Linux with a QEMU aarch64 handler registered. A smoke test confirms it runs.",
                           evidence=o.OBSERVED, detail=f"mode: {mode}; binfmt qemu-aarch64: enabled")
        return o.check(cid, o.FAIL, f"x86_64 Linux without an enabled QEMU aarch64 handler (binfmt: {binfmt}).",
                       detail=f"mode: {mode}", remediation=hostmod.QEMU_MANUAL_SETUP)
    return o.check(cid, o.UNKNOWN, f"Host {host['os']}/{host['architecture']} is not a supported workstation type.",
                   detail=f"mode: {mode}")
