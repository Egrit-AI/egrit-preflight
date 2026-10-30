"""Builds the report fixtures. `python3 -m tests.make_fixtures` rewrites tests/fixtures/reports/.

Every valid fixture is real output of the CLI, run against a scripted Docker with a fixed clock, so nothing in it is
from a real machine: the hosts, versions and digests are made up. The invalid fixtures are valid ones with one thing
broken. tests/test_contract.py fails if the committed files differ from what this module produces, so a change to the
report cannot slip past without the fixtures (and therefore the contract) being looked at.
"""

import copy
import io
import json
import os
import re
import sys
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "reports"
TARGET = str(ROOT / "examples" / "target-orin-nano-jetpack-6.2.json")

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from egrit_preflight import cli  # noqa: E402
from tests.fakes import INFO_ARM, INFO_X86, FakeRunner, bad, docker_ok, image_inspect, inspect_rule, ok  # noqa: E402

A, B, C, D = ("sha256:" + ch * 64 for ch in "abcd")
ARM_MANIFEST, ATT_MANIFEST = "sha256:" + "1" * 64, "sha256:" + "2" * 64


def _index(arch="arm64", attest=True):
    manifests = [{"digest": ARM_MANIFEST, "platform": {"os": "linux", "architecture": arch}}]
    if attest:
        manifests.append({"digest": ATT_MANIFEST, "platform": {"os": "unknown", "architecture": "unknown"},
                          "annotations": {"vnd.docker.reference.type": "attestation-manifest",
                                          "vnd.docker.reference.digest": ARM_MANIFEST}})
    return {"manifests": manifests}


def _registry(index, predicates=("https://spdx.dev/Document",)):
    def answer(argv):
        if index is None:
            return bad("registry unreachable")
        if re.search(r":sha256-[0-9a-f]{64}\.(sbom|att|sig|vex)$", argv[-1]):
            return bad("manifest unknown")  # no scenario publishes digest-named tag artefacts
        if argv[-1].endswith(ATT_MANIFEST):
            return ok(json.dumps({"layers": [{"annotations": {"in-toto.io/predicate-type": p}} for p in predicates]}))
        return ok(json.dumps(index))
    return (("docker", "buildx", "imagetools"), answer)


def _runner(info, local=None, index=None, predicates=("https://spdx.dev/Document",), smoke_out=None):
    rules = [inspect_rule(default=ok(local) if local else bad("No such image")), _registry(index, predicates)]
    if smoke_out is not None:
        rules += [(("docker", "run"), ok(smoke_out)), (("docker", "rm"), ok())]
    return FakeRunner(rules + docker_ok(info))


# name -> (argv, host system, host machine, binfmt, runner factory)
SCENARIOS = {
    "pass-observed": (
        ["report", "--json", "--image", f"example.com/app@{A}", "--smoke", "--yes"], "Linux", "aarch64", "absent",
        lambda: _runner(INFO_ARM, local=image_inspect("arm64"), index=_index(),
                        predicates=("https://spdx.dev/Document", "https://slsa.dev/provenance/v0.2"),
                        smoke_out="aarch64\n")),
    "declared-target": (
        ["report", "--json", "--image", f"registry.example/l4t/app:r36.4.0@{B}", "--target", TARGET],
        "Linux", "aarch64", "absent",
        lambda: _runner(INFO_ARM, local=image_inspect("arm64", ["CUDA_VERSION=12.6.1", "TENSORRT_VERSION=10.3.0"]),
                        index=None)),
    "unknown-registry-down": (
        ["report", "--json", "--image", f"example.com/app@{C}"], "Linux", "x86_64", "enabled",
        lambda: _runner(INFO_X86, local=None, index=None)),
    "doctor-only": (
        ["report", "--json"], "Darwin", "arm64", "absent", lambda: FakeRunner(docker_ok(INFO_ARM))),
    "fail-arch-mismatch": (
        ["report", "--json", "--image", f"example.com/app@{D}"], "Linux", "aarch64", "absent",
        lambda: _runner(INFO_ARM, local=image_inspect("amd64"), index=None)),
    "mutable-tag": (
        ["report", "--json", "--image", "example.com/app:latest"], "Linux", "aarch64", "absent",
        lambda: _runner(INFO_ARM, local=image_inspect("arm64"), index=None)),
}


def _run(name):
    argv, system, machine, binfmt, make_runner = SCENARIOS[name]
    out = io.StringIO()
    patches = [mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1793000000"}),
               mock.patch("platform.system", return_value=system), mock.patch("platform.machine", return_value=machine),
               mock.patch("platform.python_version", return_value="3.12.0"),
               mock.patch("egrit_preflight.host.binfmt_status", return_value=binfmt),
               mock.patch("egrit_preflight.smoke.uuid.uuid4", return_value=types.SimpleNamespace(hex="0" * 32))]
    for p in patches:
        p.start()
    try:
        cli.main(argv, out=out, err=io.StringIO(), runner=make_runner())
    finally:
        for p in reversed(patches):
            p.stop()
    return out.getvalue()


def valid_fixtures():
    return {name: _run(name) for name in SCENARIOS}


def _check(doc, check_id):
    return next(c for c in doc["checks"] if c["id"] == check_id)


def _dump(doc):
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _mutate(base, fn):
    doc = json.loads(base)
    fn(doc)
    return _dump(doc)


def _empty_checks(doc):
    """A report that checked nothing, otherwise self-consistent: the only defect is the empty list (#45)."""
    doc.update(checks=[], overall="PASS", requires_hardware=[], uncertainties=[])


def _drop_gpu(doc):
    """Every jetson.gpu check removed and the lists that name it kept consistent, so only its absence is wrong (#45)."""
    doc["checks"] = [c for c in doc["checks"] if c["id"] != "jetson.gpu"]
    doc["requires_hardware"] = [i for i in doc["requires_hardware"] if i != "jetson.gpu"]
    doc["uncertainties"] = [u for u in doc["uncertainties"] if u["id"] != "jetson.gpu"]


def invalid_fixtures(valid=None):
    """name -> (file text, a phrase the rejection must contain)."""
    valid = valid or valid_fixtures()
    p, d, f = valid["pass-observed"], valid["declared-target"], valid["fail-arch-mismatch"]

    def drop(key):
        return lambda doc: doc.pop(key)

    def setter(path, value):
        def fn(doc):
            node = doc
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
        return fn

    cases = {
        "unsupported-version.json": (_mutate(p, setter(["schema_version"], "2")), "unsupported schema_version"),
        "missing-version.json": (_mutate(p, drop("schema_version")), "unsupported schema_version"),
        "missing-checks.json": (_mutate(p, drop("checks")), "checks must be an array"),
        "bad-outcome.json": (_mutate(p, lambda x: x["checks"][0].update(outcome="MAYBE")), "outcome must be one of"),
        "lowercase-outcome.json": (_mutate(p, lambda x: x["checks"][0].update(outcome="pass")), "outcome must be one of"),
        "outcome-not-a-string.json": (_mutate(p, lambda x: x["checks"][0].update(outcome=[])),
                                      "outcome must be one of"),
        "requires-hardware-not-strings.json": (_mutate(p, setter(["requires_hardware"], [1, "a"])),
                                               "requires_hardware must be an array of strings"),
        "uncertainty-outcome-verified.json": (_mutate(p, lambda x: x["uncertainties"][0].update(outcome="VERIFIED")),
                                              "uncertainties[0].outcome must be one of"),
        "uncertainties-emptied.json": (_mutate(p, setter(["uncertainties"], [])),
                                       "uncertainties must list each UNKNOWN and REQUIRES_HARDWARE check"),
        "bad-evidence.json": (_mutate(p, lambda x: x["checks"][0].update(evidence="verified")), "evidence must be one of"),
        "hardware-verified-true.json": (_mutate(p, setter(["hardware_verified"], True)), "hardware_verified must be false"),
        "hardware-verified-missing.json": (_mutate(p, drop("hardware_verified")), "hardware_verified must be false"),
        "gpu-check-pass.json": (_mutate(p, lambda x: _check(x, "jetson.gpu").update(outcome="PASS")),
                                "jetson.gpu must be REQUIRES_HARDWARE"),
        "gpu-check-observed.json": (_mutate(p, lambda x: _check(x, "jetson.gpu").update(evidence="observed")),
                                    "jetson.gpu evidence must be 'none'"),
        "checks-empty.json": (_mutate(p, _empty_checks), "checks must not be empty"),
        "gpu-check-missing.json": (_mutate(p, _drop_gpu), "checks must include jetson.gpu"),
        "requires-hardware-without-gpu.json": (
            _mutate(p, lambda x: x.update(requires_hardware=[i for i in x["requires_hardware"] if i != "jetson.gpu"])),
            "requires_hardware must include jetson.gpu"),
        "requires-hardware-emptied.json": (_mutate(p, setter(["requires_hardware"], [])),
                                           "requires_hardware does not list exactly"),
        "overall-pass-over-a-fail.json": (_mutate(f, setter(["overall"], "PASS")), "overall is PASS but the checks give FAIL"),
        "signature-verified-true.json": (_mutate(p, setter(["image", "provenance", "signature_verified"], True)),
                                         "signature_verified must be false"),
        "declared-claimed-observed.json": (_mutate(d, lambda x: _check(x, "target.jetpack").update(evidence="observed")),
                                           "cannot be 'observed'"),
        "sbom-claimed-observed.json": (_mutate(p, lambda x: _check(x, "image.sbom").update(evidence="observed")),
                                       "evidence must be 'declared'"),
        "target-architecture-not-arm64.json": (_mutate(p, setter(["target", "architecture"], "linux/amd64")),
                                               "target.architecture must be 'linux/arm64'"),
        "bad-digest.json": (_mutate(p, setter(["image", "digest"], "sha256:xyz")), "image.digest must be"),
        "bad-timestamp.json": (_mutate(p, setter(["timestamp"], "yesterday")), "timestamp must be"),
        "wrong-tool.json": (_mutate(p, setter(["tool", "name"], "someone-else")), "tool.name"),
        "truncated.json": (p[:300], "not valid JSON"),
        "not-an-object.json": ("[]\n", "not a JSON object"),
        "nan-constant.json": ('{"schema_version": "1", "overall": NaN}\n', "not valid JSON"),
    }
    return cases


def main():
    valid = valid_fixtures()
    for sub in ("valid", "invalid"):
        (FIXTURES / sub).mkdir(parents=True, exist_ok=True)
        for old in (FIXTURES / sub).glob("*.json"):
            old.unlink()
    for name, text in valid.items():
        (FIXTURES / "valid" / f"{name}.json").write_text(text, encoding="utf-8")
    for name, (text, _) in invalid_fixtures(valid).items():
        (FIXTURES / "invalid" / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(valid)} valid and {len(invalid_fixtures(valid))} invalid fixtures to {FIXTURES}")


if __name__ == "__main__":
    main()
