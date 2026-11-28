"""Read the Jetson software versions visible in the current filesystem."""

import platform
import re
from pathlib import Path

from .runner import run


def inspect_device(runner=run, release_file=Path("/etc/nv_tegra_release")):
    try:
        with release_file.open(encoding="ascii", errors="replace") as stream:
            release = stream.readline(1024)
    except OSError:
        release = ""
    match = re.match(r"^#\s*R(\d+)\s*\(release\),\s*REVISION:\s*(\d+(?:\.\d+)*)(?=\s*,|\s*$)", release)
    l4t = ".".join(match.groups()) if match else None

    package = runner(["dpkg-query", "-W", "-f=${Status}\t${Version}", "nvidia-jetpack"], timeout=5)
    jetpack = None
    if package.returncode == 0:
        version = re.fullmatch(r"\S+ \S+ installed\t(?:\d+:)?(\d+(?:\.\d+)*)(?:-[\w.+~:-]+)?",
                               package.stdout.strip())
        if version:
            jetpack = version.group(1)

    return {"name": "Local software inventory", "status": "declared",
            "architecture": platform.machine() or None,
            "software": {"jetpack": jetpack, "jetson_linux": l4t}}
