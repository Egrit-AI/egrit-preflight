"""Host and Docker environment detection. Read-only: nothing here changes the machine."""

import platform
from pathlib import Path

from . import safe

BINFMT_AARCH64 = Path("/proc/sys/fs/binfmt_misc/qemu-aarch64")

QEMU_MANUAL_SETUP = (
    "Register QEMU for arm64 yourself, once, as an administrator (Egrit-Preflight never does this for you):\n"
    "  docker run --privileged --rm tonistiigi/binfmt --install arm64\n"
    "or install your distribution's qemu-user-static and binfmt packages. "
    "Review https://github.com/tonistiigi/binfmt before running a privileged container."
)


def normalise_arch(machine):
    m = (machine or "").lower()
    if m in ("x86_64", "amd64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    return m or "unknown"


def detect_host(system=None, machine=None):
    return {
        "os": (system or platform.system()).lower(),
        "architecture": normalise_arch(machine or platform.machine()),
        "python": platform.python_version(),
    }


def binfmt_status(path=BINFMT_AARCH64):
    """'enabled', 'disabled' or 'absent' for the qemu-aarch64 handler on Linux."""
    try:
        text = path.read_text()
    except (FileNotFoundError, PermissionError, OSError):
        return "absent"
    return "enabled" if text.splitlines()[:1] == ["enabled"] else "disabled"


def execution_mode(host, daemon_arch, binfmt):
    """How linux/arm64 containers would run here. daemon_arch is Docker's own report, or None if unknown."""
    os_, arch = host["os"], host["architecture"]
    if daemon_arch == "arm64" and os_ == "linux":
        return "linux-arm64-native"
    if os_ == "darwin":
        if arch == "arm64" or daemon_arch == "arm64":
            return "macos-apple-silicon-vm"
        return "macos-intel-docker-desktop-emulation"
    if os_ == "linux" and arch == "x86_64":
        return "linux-x86_64-qemu"
    return "unsupported-host"


def parse_docker_info(text):
    info = safe.loads(text)
    return info if isinstance(info, dict) else None


def first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""
