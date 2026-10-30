"""The report contract, as code: what a consumer of a Preflight report may rely on, and how to read one safely.

This is a reference implementation of docs/report-contract.md. It uses the standard library only, makes no network
call and needs no account. A consumer written in another language should follow the document and use the fixtures in
tests/fixtures/reports/ as its test data.

Reading is fail closed: a report that is too large, not valid JSON, from an unsupported schema version, or that breaks
any rule below is rejected whole. Nothing is partly accepted.
"""

import json
import re

SUPPORTED_SCHEMA_VERSIONS = ("1",)
MAX_REPORT_BYTES = 1024 * 1024
MAX_CHECKS = 200
MAX_TEXT = 4000

OUTCOMES = ("PASS", "FAIL", "UNKNOWN", "REQUIRES_HARDWARE")
UNCERTAIN = ("UNKNOWN", "REQUIRES_HARDWARE")
EVIDENCE = ("observed", "declared", "none")
OVERALL = ("PASS", "FAIL", "UNKNOWN")
SECTIONS = ("doctor", "image", "smoke")

TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
CHECK_ID_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,79}")

# What a consumer may import. Everything else in a report is text that came from the machine, the image or a registry
# (check `detail` and `command`, the top-level `commands`, image labels and environment values, `limitations`). It is
# useful to a person reading the report and is not a safe thing to import or upload automatically.
ALLOWLIST = {
    "schema_version": True,
    "tool": {"name": True, "version": True},
    "timestamp": True,
    "hardware_verified": True,
    "overall": True,
    "requires_hardware": True,
    "host": {"os": True, "architecture": True, "execution_mode": True},
    "docker": {"cli_version": True, "daemon_version": True, "buildx_version": True, "daemon_architecture": True},
    "target": {"architecture": True, "record": {"jetpack": True, "jetson_linux": True, "status": True}},
    "image": {"reference": True, "digest": True, "architecture": True, "platforms": True,
              "provenance": {"status": True, "signature_verified": True,
                             "attestations": [{"predicate_types": True, "subject_digest": True}]}},
    "checks": [{"id": True, "section": True, "outcome": True, "evidence": True, "summary": True}],
    "uncertainties": [{"id": True, "section": True, "outcome": True, "summary": True}],
    "provenance": {"smoke_executed": True},
}


class Rejected(Exception):
    """The report cannot be accepted. str() lists every reason found."""


def load_report(data):
    """Parse report bytes or text. Returns (document, problems); the document is None if anything is wrong."""
    try:
        raw = data.encode("utf-8") if isinstance(data, str) else data
    except UnicodeEncodeError:
        return None, ["report is not valid UTF-8 text"]
    if len(raw) > MAX_REPORT_BYTES:
        return None, [f"report is larger than {MAX_REPORT_BYTES} bytes"]

    def refuse_constant(name):
        raise ValueError(f"non-standard JSON constant {name}")

    try:
        doc = json.loads(raw.decode("utf-8"), parse_constant=refuse_constant)
    except RecursionError:
        return None, ["report is nested too deeply"]
    except (ValueError, UnicodeDecodeError) as exc:
        return None, [f"not valid JSON ({type(exc).__name__})"]
    problems = check_report(doc)
    return (None, problems) if problems else (doc, [])


def check_report(doc):
    """Every reason the document is not an acceptable report. An empty list means it is."""
    if not isinstance(doc, dict):
        return ["report is not a JSON object"]
    version = doc.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        return [f"unsupported schema_version {version!r} (supported: {', '.join(SUPPORTED_SCHEMA_VERSIONS)})"]

    problems = []

    def need(cond, message):
        if not cond:
            problems.append(message)
        return cond

    tool = doc.get("tool")
    if need(isinstance(tool, dict), "tool must be an object"):
        need(tool.get("name") == "egrit-preflight", "tool.name must be 'egrit-preflight'")
        need(isinstance(tool.get("version"), str) and 0 < len(tool["version"]) <= 40, "tool.version must be a string")
    need(isinstance(doc.get("timestamp"), str) and bool(TIMESTAMP_RE.fullmatch(doc["timestamp"])),
         "timestamp must be UTC to the second, like 2026-10-26T12:00:00Z")
    need(doc.get("hardware_verified") is False,
         "hardware_verified must be false: this tool never verifies hardware")
    need(doc.get("overall") in OVERALL, f"overall must be one of {OVERALL}")
    for key in ("host", "docker", "target", "provenance"):
        need(isinstance(doc.get(key), dict), f"{key} must be an object")
    if isinstance(doc.get("target"), dict):
        need(doc["target"].get("architecture") == "linux/arm64",
             "target.architecture must be 'linux/arm64': a version 1 report is about linux/arm64 only")
    need(doc.get("image") is None or isinstance(doc.get("image"), dict), "image must be an object or null")
    for key in ("limitations", "uncertainties", "commands", "requires_hardware"):
        need(isinstance(doc.get(key), list), f"{key} must be an array")
    need(isinstance(doc.get("limitations"), list) and len(doc["limitations"]) > 0
         and all(isinstance(x, str) for x in doc["limitations"]), "limitations must be a non-empty array of strings")

    checks = doc.get("checks")
    if need(isinstance(checks, list), "checks must be an array") and checks is not None:
        need(len(checks) <= MAX_CHECKS, f"more than {MAX_CHECKS} checks")
        for i, c in enumerate(checks[:MAX_CHECKS]):
            where = f"checks[{i}]"
            if not need(isinstance(c, dict), f"{where} must be an object"):
                continue
            need(isinstance(c.get("id"), str) and bool(CHECK_ID_RE.fullmatch(c["id"])), f"{where}.id is not a valid id")
            need(c.get("section") in SECTIONS, f"{where}.section must be one of {SECTIONS}")
            need(c.get("outcome") in OUTCOMES, f"{where}.outcome must be one of {OUTCOMES}")
            need(c.get("evidence") in EVIDENCE, f"{where}.evidence must be one of {EVIDENCE}")
            need(isinstance(c.get("summary"), str) and len(c["summary"]) <= MAX_TEXT, f"{where}.summary must be text")
        problems += _invariants(doc, [c for c in checks[:MAX_CHECKS] if isinstance(c, dict)])

    uncertainties = doc.get("uncertainties")
    if isinstance(uncertainties, list):
        # Rule 10 (egrit-preflight #32): an uncertainty is a record of a check that is UNKNOWN or REQUIRES_HARDWARE,
        # once per id and outcome. allowlisted_view exports these fields, so an unchecked word here would reach a
        # consumer as data the contract does not define.
        pairs = []
        for i, u in enumerate(uncertainties[:MAX_CHECKS]):
            where = f"uncertainties[{i}]"
            if not need(isinstance(u, dict), f"{where} must be an object"):
                continue
            need(isinstance(u.get("id"), str) and bool(CHECK_ID_RE.fullmatch(u["id"])), f"{where}.id is not a valid id")
            need(u.get("section") in SECTIONS, f"{where}.section must be one of {SECTIONS}")
            if need(u.get("outcome") in UNCERTAIN, f"{where}.outcome must be one of {UNCERTAIN}"):
                if isinstance(u.get("id"), str):
                    pairs.append((u["id"], u["outcome"]))
            need(isinstance(u.get("summary"), str) and len(u["summary"]) <= MAX_TEXT, f"{where}.summary must be text")
        need(len(uncertainties) <= MAX_CHECKS, f"more than {MAX_CHECKS} uncertainties")
        if isinstance(checks, list):
            expected = {(c["id"], c["outcome"]) for c in checks[:MAX_CHECKS] if isinstance(c, dict)
                        and isinstance(c.get("id"), str) and c.get("outcome") in UNCERTAIN}
            need(len(pairs) == len(set(pairs)) and set(pairs) == expected,
                 "uncertainties must list each UNKNOWN and REQUIRES_HARDWARE check once per id and outcome")

    image = doc.get("image")
    if isinstance(image, dict):
        need(image.get("digest") is None or (isinstance(image.get("digest"), str)
                                             and bool(DIGEST_RE.fullmatch(image["digest"]))),
             "image.digest must be null or sha256:<64 hex digits>")
        prov = image.get("provenance")
        if prov is not None:
            need(isinstance(prov, dict) and prov.get("signature_verified") is False,
                 "image.provenance.signature_verified must be false: this tool never verifies signatures")
    return problems


def _invariants(doc, checks):
    """The rules JSON Schema cannot state: what a report must never claim."""
    problems = []
    # Only string outcomes take part: a non-string one is already reported by the enum check, and must not crash
    # the set below (an unhashable list or dict raised TypeError here, egrit-preflight #31).
    outcomes = {o for o in (c.get("outcome") for c in checks) if isinstance(o, str)}
    expected_overall = "FAIL" if "FAIL" in outcomes else "UNKNOWN" if "UNKNOWN" in outcomes else "PASS"
    if doc.get("overall") in OVERALL and doc["overall"] != expected_overall:
        problems.append(f"overall is {doc['overall']} but the checks give {expected_overall}")
    hw = sorted({c["id"] for c in checks if c.get("outcome") == "REQUIRES_HARDWARE" and isinstance(c.get("id"), str)})
    listed = doc.get("requires_hardware")
    if isinstance(listed, list):
        if not all(isinstance(x, str) for x in listed):
            # sorted() over mixed types raised TypeError here (egrit-preflight #31); the schema requires strings.
            problems.append("requires_hardware must be an array of strings")
        elif sorted(listed) != hw:
            problems.append("requires_hardware does not list exactly the REQUIRES_HARDWARE checks")
    for c in checks:
        cid, outcome, evidence = c.get("id"), c.get("outcome"), c.get("evidence")
        if cid == "jetson.gpu" and outcome != "REQUIRES_HARDWARE":
            problems.append("jetson.gpu must be REQUIRES_HARDWARE: a GPU result cannot come from this tool")
        if cid == "jetson.gpu" and evidence != "none":
            # egrit-preflight #44: the writer always says "none"; observed or declared would read as GPU evidence.
            problems.append("jetson.gpu evidence must be 'none': this tool neither observes nor reads a GPU result")
        if isinstance(cid, str) and cid.startswith(("runtime.", "target.")) and evidence == "observed":
            problems.append(f"{cid} compares declared values and cannot be 'observed'")
        if cid in ("image.sbom", "image.provenance") and outcome == "PASS" and evidence != "declared":
            problems.append(f"{cid} is a registry declaration, not verified: evidence must be 'declared'")
    # egrit-preflight #45: a report that checked nothing, or left out the GPU check, must not read as a clean PASS.
    if not checks:
        problems.append("checks must not be empty: a report that checked nothing cannot pass")
    elif not any(c.get("id") == "jetson.gpu" for c in checks):
        problems.append("checks must include jetson.gpu: every report lists the GPU check it cannot run")
    if isinstance(listed, list) and all(isinstance(x, str) for x in listed) and "jetson.gpu" not in listed:
        problems.append("requires_hardware must include jetson.gpu")
    return problems


def allowlisted_view(doc, allow=ALLOWLIST):
    """The part of a (valid) report a consumer may import. Raises Rejected if the report is not acceptable."""
    problems = check_report(doc)
    if problems:
        raise Rejected("; ".join(problems))
    return _pick(doc, allow)


def _pick(value, allow):
    if allow is True:
        return value
    if isinstance(allow, dict):
        if not isinstance(value, dict):
            return None
        return {k: _pick(value[k], sub) for k, sub in allow.items() if k in value}
    if isinstance(allow, list):
        if not isinstance(value, list):
            return None
        return [_pick(item, allow[0]) for item in value]
    return None
