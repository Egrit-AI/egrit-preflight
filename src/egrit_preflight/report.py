"""The machine-readable report. Same inputs and SOURCE_DATE_EPOCH give byte-identical output."""

import datetime
import hashlib
import json
import os
import platform

from . import __version__
from . import outcomes as o
from . import safe

SCHEMA_VERSION = "1"
STANDING_LIMITS = [
    "ARM64 user-space emulation or a native ARM64 run is not a Jetson run.",
    "CUDA, TensorRT, the NVIDIA driver, device nodes and GPU performance are not tested.",
    "Declared versions (target records, image tags and labels) are not observed on a device.",
    "A mocked or emulated result is never hardware verification.",
]


def timestamp(env=os.environ, now=None):
    epoch = env.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        t = datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc)
    else:
        t = now or datetime.datetime.now(datetime.timezone.utc)
    return t.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_sha256(path):
    try:
        return "sha256:" + hashlib.sha256(safe.read_small_file(path)).hexdigest()
    except OSError:
        return None


def build_report(doctor, image=None, smoke=None, target_path=None, env=os.environ, now=None):
    sections = {"doctor": doctor["checks"]}
    if image:
        sections["image"] = image["checks"]
    if smoke:
        sections["smoke"] = smoke["checks"]
    checks = [dict(c, section=s) for s, cs in sections.items() for c in cs]
    uncertain = [{"id": c["id"], "section": c["section"], "outcome": c["outcome"], "summary": c["summary"]}
                 for c in checks if c["outcome"] in (o.UNKNOWN, o.REQUIRES_HARDWARE)]
    # One standing GPU entry is enough; the same line three times adds nothing.
    seen, dedup = set(), []
    for u in uncertain:
        key = (u["id"], u["outcome"])
        if key not in seen:
            seen.add(key)
            dedup.append(u)
    ref = (image or smoke or {}).get("reference")
    report = {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "egrit-preflight", "version": __version__},
        "timestamp": timestamp(env, now),
        "host": dict(doctor["host"], execution_mode=doctor["arm64_execution_mode"],
                     binfmt_qemu_aarch64=doctor["binfmt_qemu_aarch64"]),
        "docker": doctor["docker"],
        "target": {"architecture": "linux/arm64", "record": (image or {}).get("target")},
        "image": {"reference": ref, "digest": (image or smoke or {}).get("digest"),
                  "architecture": (image or {}).get("architecture"),
                  "platforms": (image or {}).get("platforms"),
                  "declared_dependencies": (image or {}).get("declared_dependencies"),
                  "provenance": (image or {}).get("provenance")} if ref else None,
        "checks": checks,
        "commands": [c["command"] for c in checks if "command" in c],
        "overall": o.overall(checks),
        # Always false. `overall` can be PASS while checks still need a device, so this says it outright.
        "hardware_verified": False,
        "requires_hardware": sorted({c["id"] for c in checks if c["outcome"] == o.REQUIRES_HARDWARE}),
        "uncertainties": dedup,
        "limitations": STANDING_LIMITS,
        "provenance": {
            "generated_by": f"egrit-preflight {__version__}", "python": platform.python_version(),
            "inputs": {"image_reference": ref, "target_record_sha256": file_sha256(target_path) if target_path else None},
            "smoke_executed": bool(smoke and smoke.get("executed")),
            "telemetry": "none; this tool sends nothing anywhere",
        },
    }
    return report


def dumps(report):
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
