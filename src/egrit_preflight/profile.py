"""The vendor target profile, as code: a companion record for one identified hardware and software configuration.

This is a reference implementation of docs/vendor-target-profile.md. It uses the standard library only, makes no
network call and needs no account. No command of the CLI reads a profile: `--target` still takes the small target
record, and a report stays schema version 1 with `hardware_verified: false`.

A profile holds statements, not conclusions. Each statement names its value, its evidence grade, its source and the
configuration revision it is about. Reading is fail closed, and three rules hold everywhere below:

- a value that is missing, contradicted or stated for another revision is never used, so it can only give UNKNOWN;
- nothing here returns a compatibility PASS, and an accelerator or a required interface is always REQUIRES_HARDWARE;
- a statement graded `observed` is exported as `declared`, because a version 1 report has no observed target check.
"""

import json
import re

from . import outcomes as o

DOCUMENT = "egrit-preflight vendor target profile"
SUPPORTED_PROFILE_VERSIONS = ("1",)
MAX_PROFILE_BYTES = 1024 * 1024
MAX_STATEMENTS = 20
MAX_LIST = 50
MAX_TEXT = 400

IDENTITY = ("vendor", "product", "model", "module", "hardware_revision", "software_revision", "profile_revision")
REVISIONS = ("hardware_revision", "software_revision")
FACTS = ("architecture", "os_distribution", "os_build", "abi", "jetpack", "jetson_linux", "cuda", "tensorrt",
         "container_runtime")
EVIDENCE = (o.OBSERVED, o.DECLARED, o.NONE)
ARM64 = ("aarch64", "arm64")

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
URL_RE = re.compile(r"https://[^\s\x00-\x1f\x7f]{1,1000}")
INTERFACE_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,59}")

STATED = "stated"
MISSING = "missing"
CONTRADICTORY = "contradictory"
NOT_ESTABLISHED = "not established"


def load_profile(data):
    """Parse profile bytes or text. Returns (document, problems); the document is None if anything is wrong."""
    try:
        raw = data.encode("utf-8") if isinstance(data, str) else data
    except UnicodeEncodeError:
        return None, ["profile is not valid UTF-8 text"]
    if len(raw) > MAX_PROFILE_BYTES:
        return None, [f"profile is larger than {MAX_PROFILE_BYTES} bytes"]

    def refuse_constant(name):
        raise ValueError(f"non-standard JSON constant {name}")

    try:
        doc = json.loads(raw.decode("utf-8"), parse_constant=refuse_constant)
    except RecursionError:
        return None, ["profile is nested too deeply"]
    except (ValueError, UnicodeDecodeError) as exc:
        return None, [f"not valid JSON ({type(exc).__name__})"]
    problems = check_profile(doc)
    return (None, problems) if problems else (doc, [])


def _text(value):
    return isinstance(value, str) and 0 < len(value) <= MAX_TEXT and value == value.strip() and value.isprintable()


def _text_or_null(value):
    return value is None or _text(value)


def _check_source(where, item, problems, needs_value):
    """The source half of a statement or an equivalence: grade, URL and date agree with each other."""
    evidence = item.get("evidence")
    if evidence not in EVIDENCE:
        problems.append(f"{where}.evidence must be one of {list(EVIDENCE)}")
        return
    url, date = item.get("source_url"), item.get("retrieved")
    if url is not None and not (isinstance(url, str) and URL_RE.fullmatch(url)):
        problems.append(f"{where}.source_url must be an https URL or null")
    if date is not None and not (isinstance(date, str) and DATE_RE.fullmatch(date)):
        problems.append(f"{where}.retrieved must be YYYY-MM-DD or null")
    if evidence == o.NONE:
        if needs_value:
            problems.append(f"{where}: a value needs evidence 'declared' or 'observed'")
        return
    if not needs_value:
        problems.append(f"{where}: evidence {evidence!r} needs a value; a missing value has evidence 'none'")
    if date is None:
        problems.append(f"{where}: evidence {evidence!r} needs a retrieved date")
    if evidence == o.DECLARED and url is None:
        problems.append(f"{where}: a declared value needs a source_url")


def _check_applies_to(where, item, problems):
    applies = item.get("applies_to")
    if not isinstance(applies, dict):
        problems.append(f"{where}.applies_to must be an object naming hardware_revision and software_revision")
        return
    for key in REVISIONS:
        if key not in applies or not _text_or_null(applies[key]):
            problems.append(f"{where}.applies_to.{key} must be a string or null")


def check_profile(doc):
    """Every reason the document is not an acceptable profile. An empty list means it is."""
    if not isinstance(doc, dict):
        return ["profile must be a JSON object"]
    problems = []
    if doc.get("document") != DOCUMENT:
        problems.append(f"document must be {DOCUMENT!r}")
    if doc.get("profile_version") not in SUPPORTED_PROFILE_VERSIONS:
        problems.append(f"profile_version must be one of {list(SUPPORTED_PROFILE_VERSIONS)}")
    if "synthetic" in doc and not isinstance(doc["synthetic"], bool):
        problems.append("synthetic must be true or false")

    identity = doc.get("identity")
    if not isinstance(identity, dict):
        problems.append("identity must be an object")
    else:
        for key in IDENTITY:
            if key not in identity:
                problems.append(f"identity.{key} is missing; write null for a value that is not established")
            elif key in ("vendor", "product", "profile_revision"):
                if not _text(identity[key]):
                    problems.append(f"identity.{key} must be a non-empty string")
            elif not _text_or_null(identity[key]):
                problems.append(f"identity.{key} must be a string or null")

    facts = doc.get("facts")
    if not isinstance(facts, dict):
        problems.append("facts must be an object")
    else:
        for name in sorted(set(facts) - set(FACTS)):
            problems.append(f"facts: {name[:40]!r} is not a known fact")
        for name in FACTS:
            statements = facts.get(name)
            if not isinstance(statements, list) or len(statements) > MAX_STATEMENTS:
                problems.append(f"facts.{name} must be a list of at most {MAX_STATEMENTS} statements; "
                                "an empty list means nothing is stated")
                continue
            for i, s in enumerate(statements):
                where = f"facts.{name}[{i}]"
                if not isinstance(s, dict):
                    problems.append(f"{where} must be an object")
                    continue
                if "value" not in s or not _text_or_null(s["value"]):
                    problems.append(f"{where}.value must be a string or null")
                    continue
                if s["value"] is not None and s["value"].lower() in (NOT_ESTABLISHED, "unknown"):
                    problems.append(f"{where}.value: write null for a value that is not established")
                _check_source(where, s, problems, needs_value=s["value"] is not None)
                _check_applies_to(where, s, problems)

    interfaces = doc.get("required_interfaces")
    if not isinstance(interfaces, list) or len(interfaces) > MAX_LIST:
        problems.append(f"required_interfaces must be a list of at most {MAX_LIST} names")
    else:
        for i, name in enumerate(interfaces):
            if not (isinstance(name, str) and INTERFACE_RE.fullmatch(name)):
                problems.append(f"required_interfaces[{i}] must match {INTERFACE_RE.pattern}")
        if len(set(map(str, interfaces))) != len(interfaces):
            problems.append("required_interfaces must not repeat a name")

    equivalences = doc.get("equivalences", [])
    if not isinstance(equivalences, list) or len(equivalences) > MAX_LIST:
        problems.append(f"equivalences must be a list of at most {MAX_LIST} statements")
    else:
        for i, e in enumerate(equivalences):
            where = f"equivalences[{i}]"
            if not isinstance(e, dict):
                problems.append(f"{where} must be an object")
                continue
            other = e.get("identity")
            if not (isinstance(other, dict) and set(other) == set(IDENTITY) and all(_text(v) for v in other.values())):
                problems.append(f"{where}.identity must give every identity field as a non-empty string")
            fields = e.get("fields")
            if not (isinstance(fields, list) and fields and all(isinstance(f, str) and f in FACTS for f in fields)):
                problems.append(f"{where}.fields must be a non-empty list of known facts")
            _check_source(where, e, problems, needs_value=True)
    return problems


def _require(doc):
    problems = check_profile(doc)
    if problems:
        raise ValueError("not an acceptable profile: " + "; ".join(problems))


def _applies(statement, identity):
    """A statement counts only for the exact revisions the profile identifies. A null revision matches nothing."""
    return all(identity[k] is not None and statement["applies_to"][k] == identity[k] for k in REVISIONS)


def resolve(doc, fact):
    """What the profile establishes about one fact for its own configuration.

    Returns a dict: `state` is `stated` (exactly one distinct value, in `value`), `missing` or `contradictory`;
    `statements` are the applicable statements that carry a value, all of them, so a conflict keeps both sources;
    `set_aside` counts the statements with a value that are about another revision.
    """
    _require(doc)
    with_value = [s for s in doc["facts"][fact] if s["value"] is not None]
    used = [s for s in with_value if _applies(s, doc["identity"])]
    values = sorted({s["value"] for s in used})
    state = STATED if len(values) == 1 else CONTRADICTORY if values else MISSING
    return {"state": state, "value": values[0] if state == STATED else None, "statements": used,
            "set_aside": len(with_value) - len(used)}


def _sources(statements):
    return "; ".join(f"{s['value']!r} ({s['evidence']}, {s['source_url'] or 'no URL'}, {s['retrieved']})"
                     for s in statements)


def assess_profile(doc):
    """Validate one profile against the linux/arm64 requirement. Not a compatibility result.

    Returns `checks` (the four outcome words), `complete` (every fact stated once and no FAIL), and the two constants
    `compatibility_established` and `hardware_verified`, both always False. The only PASS is `profile.architecture`
    when the profile states an ARM64 architecture, with the grade `declared`, as a version 1 report does.
    """
    _require(doc)
    identity = doc["identity"]
    checks = []
    for key in ("model", "module", *REVISIONS):
        if identity[key] is None:
            checks.append(o.check(f"profile.identity.{key}", o.UNKNOWN,
                                  f"The profile does not establish its {key.replace('_', ' ')}.",
                                  remediation="State it from a source that names it; do not infer it from the "
                                              "product family." if key in REVISIONS else None))
    for fact in FACTS:
        found = resolve(doc, fact)
        cid = f"profile.{fact}"
        aside = (f" {found['set_aside']} statement(s) about another revision were not used."
                 if found["set_aside"] else "")
        if found["state"] == CONTRADICTORY:
            checks.append(o.check(cid, o.UNKNOWN, f"Sources disagree about {fact}; neither is preferred.{aside}",
                                  detail=_sources(found["statements"])))
        elif found["state"] == MISSING:
            checks.append(o.check(cid, o.UNKNOWN, f"Nothing states {fact} for this configuration.{aside}"))
        elif fact == "architecture":
            arm = found["value"].lower() in ARM64
            checks.append(o.check(cid, o.PASS if arm else o.FAIL,
                                  f"The profile states architecture {found['value']}."
                                  + ("" if arm else " Preflight covers linux/arm64 only."), evidence=o.DECLARED))
    checks.append(o.check("profile.gpu", o.REQUIRES_HARDWARE,
                          "The GPU, its driver and its container runtime need the physical device."))
    for name in doc["required_interfaces"]:
        checks.append(o.check(f"profile.interface.{name}", o.REQUIRES_HARDWARE,
                              f"The interface {name} needs the physical device."))
    return {"checks": checks, "complete": not any(c["outcome"] in (o.FAIL, o.UNKNOWN) for c in checks),
            "compatibility_established": False, "hardware_verified": False}


def equivalent(a, b, fields):
    """Whether profile `a` may be read as `b` for `fields`. Returns (answer, reason).

    True only for the same fully identified configuration, or where `a` carries a sourced equivalence statement that
    names every identity field of `b` and covers every compared field. A shared vendor, product family or module is
    never enough, and nothing is inherited.
    """
    _require(a)
    _require(b)
    fields = list(fields)
    if not fields or any(f not in FACTS for f in fields):
        return False, "the compared fields must be known facts"
    ia, ib = a["identity"], b["identity"]
    for name, identity in (("first", ia), ("second", ib)):
        unknown = [k for k in IDENTITY if identity[k] is None]
        if unknown:
            return False, f"the {name} profile does not establish its {', '.join(unknown)}"
    if all(ia[k] == ib[k] for k in IDENTITY):
        return True, "the same identified configuration"
    for e in a.get("equivalences", []):
        if e["identity"] == ib:
            uncovered = [f for f in fields if f not in e["fields"]]
            if uncovered:
                return False, f"the equivalence statement does not cover {', '.join(uncovered)}"
            return True, f"equivalence stated by {e['source_url'] or 'a device observation'} ({e['retrieved']})"
    differs = [k for k in IDENTITY if ia[k] != ib[k]]
    return False, f"the configurations differ in {', '.join(differs)} and no equivalence statement covers them"


def to_target_record(doc):
    """The small record `--target` reads today, from the facts this profile states exactly once.

    A fact that is missing or contradictory is written "not established", which the CLI reports as UNKNOWN, and a
    profile with no stated architecture exports none. `status` is always "declared", whatever grade the statements
    carry. The record does not carry the profile's identity or ABI into a report: the CLI compares neither.
    """
    _require(doc)
    identity = doc["identity"]
    found = {f: resolve(doc, f) for f in ("architecture", "jetpack", "jetson_linux", "cuda", "tensorrt")}

    def value(fact):
        return found[fact]["value"] if found[fact]["state"] == STATED else NOT_ESTABLISHED

    label = " ".join(str(identity[k]) for k in ("vendor", "product", "model") if identity[k])
    record = {"name": f"{label}, profile {identity['profile_revision']} (declared, not read from a device)"}
    if found["architecture"]["state"] == STATED:
        record["architecture"] = found["architecture"]["value"]
    record["software"] = {"jetpack": value("jetpack"), "jetson_linux": value("jetson_linux")}
    record["runtimes"] = {"cuda": value("cuda"), "tensorrt": value("tensorrt")}
    record["status"] = o.DECLARED
    record["sources"] = [{"what": f"{fact}: {s['value']}", "url": s["source_url"], "retrieved": s["retrieved"]}
                         for fact, r in found.items() if r["state"] == STATED for s in r["statements"]]
    return record
