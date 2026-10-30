"""Hypothesis strategies for the report reader: edited fixtures, arbitrary JSON, raw bytes and documents near 1 MiB.

Every strategy here produces inputs only. The judgement of what the reader should do with them lives in
test_properties.py. A generated document records which fixture it came from and which edits were applied, so a
counterexample can be read without re-running anything.
"""

import copy
import json
from collections import namedtuple

from hypothesis import strategies as st

from assurance.preflight import FIXTURES

MAX_REPORT_BYTES = 1024 * 1024
OUTCOMES = ("PASS", "FAIL", "UNKNOWN", "REQUIRES_HARDWARE")
EVIDENCE = ("observed", "declared", "none")
OVERALL = ("PASS", "FAIL", "UNKNOWN")
SECTIONS = ("doctor", "image", "smoke")
ENUM_KEYS = ("outcome", "evidence", "overall", "section", "status")
# Words a careless or hostile producer might use. "VERIFIED" is the one the contract says must never be accepted.
UNKNOWN_WORDS = ("VERIFIED", "verified", "pass", "OK", "PASSED", "Observed", "attested", "", "PASS ", "REQUIRES_HW")

Generated = namedtuple("Generated", "fixture edits doc")
Edit = namedtuple("Edit", "kind path value")


_CACHE = []


def valid_fixtures():
    """The six valid fixtures as (name, document); a deep copy each call, so a caller may edit in place."""
    if not _CACHE:
        for path in sorted((FIXTURES / "valid").glob("*.json")):
            with open(path, "rb") as fh:
                _CACHE.append((path.name, json.load(fh)))
    return copy.deepcopy(_CACHE)


def invalid_fixtures():
    """Every invalid fixture as (name, raw bytes); some are not JSON at all."""
    return [(p.name, p.read_bytes()) for p in sorted((FIXTURES / "invalid").glob("*.json"))]


def paths(value, prefix=()):
    """Every path to a node in a JSON tree, parents before children, as tuples of keys and indexes."""
    out = [prefix]
    if isinstance(value, dict):
        for key in value:
            out.extend(paths(value[key], prefix + (key,)))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            out.extend(paths(item, prefix + (i,)))
    return out


def get_at(doc, path):
    node = doc
    for step in path:
        node = node[step]
    return node


def set_at(doc, path, value):
    if not path:
        return value
    parent = get_at(doc, path[:-1])
    parent[path[-1]] = value
    return doc


def delete_at(doc, path):
    if not path:
        return None
    parent = get_at(doc, path[:-1])
    del parent[path[-1]]
    return doc


json_scalars = st.one_of(st.none(), st.booleans(), st.integers(min_value=-2**53, max_value=2**53),
                         st.floats(allow_nan=False, allow_infinity=False, width=32), st.text(max_size=12))


def json_trees(max_leaves=30):
    """Arbitrary finite JSON values: scalars, lists and string-keyed objects, nested."""
    return st.recursive(json_scalars,
                        lambda inner: st.one_of(st.lists(inner, max_size=5),
                                                st.dictionaries(st.text(max_size=8), inner, max_size=5)),
                        max_leaves=max_leaves)


edit_kinds = st.sampled_from(("type_swap", "enum_swap", "extra_key", "unicode", "list_or_dict", "delete", "drop_gpu", "gpu_evidence"))
unicode_text = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=24)
enum_words = st.sampled_from(OUTCOMES + EVIDENCE + OVERALL + SECTIONS + UNKNOWN_WORDS)


@st.composite
def edits(draw):
    """One edit, described abstractly; `apply_edit` resolves the path against the document it is given."""
    kind = draw(edit_kinds)
    which = draw(st.integers(min_value=0, max_value=4095))
    if kind == "type_swap":
        value = draw(st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=6), st.sampled_from(("false", 0, 1, "true"))))
    elif kind == "enum_swap":
        value = draw(enum_words)
    elif kind == "extra_key":
        value = (draw(st.one_of(st.text(max_size=10), st.sampled_from(("verified", "hardware_verified", "signature_verified")))),
                 draw(st.one_of(json_scalars, st.just([]), st.just({}))))
    elif kind == "unicode":
        value = draw(unicode_text)
    elif kind == "list_or_dict":
        value = draw(st.one_of(st.just([]), st.just({}), st.lists(json_scalars, max_size=3), st.dictionaries(st.text(max_size=4), json_scalars, max_size=3)))
    else:
        value = None
    return Edit(kind, which, value)


def _target_path(doc, edit):
    all_paths = paths(doc)
    if edit.kind == "enum_swap":
        candidates = [p for p in all_paths if p and p[-1] in ENUM_KEYS] or all_paths
    elif edit.kind == "extra_key":
        candidates = [p for p in all_paths if isinstance(get_at(doc, p), dict)]
    else:
        candidates = [p for p in all_paths if p]  # never replace the root with a scalar here; json_trees covers that
    return candidates[edit.path % len(candidates)]


def apply_edit(doc, edit):
    """Apply one edit to a document in place and return the concrete (kind, path, value) that was applied."""
    if edit.kind == "gpu_evidence":
        # The jetson.gpu checks' evidence set to a drawn word (#44), so PF-1 meets observed and declared GPU checks.
        word = EVIDENCE[edit.path % len(EVIDENCE)]
        for c in doc.get("checks") or []:
            if isinstance(c, dict) and c.get("id") == "jetson.gpu":
                c["evidence"] = word
        return Edit(edit.kind, ("checks",), word)
    if edit.kind == "drop_gpu":
        # Every jetson.gpu check removed and the lists that name it kept consistent (#45): a report that is
        # otherwise self-consistent, so only rule 11 stands between it and acceptance.
        for key in ("checks", "uncertainties"):
            if isinstance(doc.get(key), list):
                doc[key] = [c for c in doc[key] if not (isinstance(c, dict) and c.get("id") == "jetson.gpu")]
        if isinstance(doc.get("requires_hardware"), list):
            doc["requires_hardware"] = [i for i in doc["requires_hardware"] if i != "jetson.gpu"]
        return Edit(edit.kind, ("checks",), None)
    path = _target_path(doc, edit)
    if edit.kind == "extra_key":
        key, value = edit.value
        get_at(doc, path)[key] = value
        return Edit(edit.kind, path + (key,), value)
    if edit.kind == "delete":
        delete_at(doc, path)
        return Edit(edit.kind, path, None)
    set_at(doc, path, copy.deepcopy(edit.value))
    return Edit(edit.kind, path, edit.value)


def _names():
    return [name for name, _ in valid_fixtures()]


@st.composite
def edited_reports(draw):
    """A valid fixture with 0 to 3 edits applied. Returns Generated(fixture, applied_edits, doc)."""
    index = draw(st.integers(min_value=0, max_value=len(_names()) - 1))
    name, doc = valid_fixtures()[index]
    applied = []
    for edit in draw(st.lists(edits(), min_size=0, max_size=3)):
        applied.append(apply_edit(doc, edit))
    return Generated(name, tuple(applied), doc)


def reports():
    """Just the document from `edited_reports`."""
    return edited_reports().map(lambda g: g.doc)


def surrogate_text():
    """Text that holds at least one lone surrogate, which `str.encode("utf-8")` refuses."""
    lone = st.sampled_from(["\ud800", "\udbff", "\udc00", "\udfff"])
    return st.tuples(st.text(max_size=8), lone, st.text(max_size=8)).map(lambda parts: "".join(parts))


def raw_bytes():
    """Arbitrary bytes, biased towards things that look like the start of JSON, and text with a lone surrogate."""
    return st.one_of(st.binary(max_size=64), surrogate_text(),
                     st.sampled_from([b"", b"{", b"[", b"null", b"NaN", b"{\"schema_version\": \"1\"", b"\xff\xfe", b"{}"]),
                     st.text(max_size=64).map(lambda s: s.encode("utf-8")))


def near_limit():
    """A valid fixture serialised with padding so the byte length sits at the 1 MiB limit minus 1, exactly, or plus 1.

    Padding goes in a string the reader does not read (`limitations[0]` is text for people). Three sizes only, so a
    run stays fast: one example is about a megabyte.
    """
    def pad(args):
        (name, doc), delta = args
        target = MAX_REPORT_BYTES + delta
        base = json.dumps(doc, separators=(",", ":")).encode("utf-8")
        doc["limitations"][0] = doc["limitations"][0] + "x" * (target - len(base))
        raw = json.dumps(doc, separators=(",", ":")).encode("utf-8")
        assert len(raw) == target, (len(raw), target)
        return name, delta, raw
    return st.tuples(st.integers(min_value=0, max_value=len(_names()) - 1), st.sampled_from((-1, 0, 1))).map(
        lambda args: pad((valid_fixtures()[args[0]], args[1])))


def serialised(doc):
    return json.dumps(doc, ensure_ascii=False).encode("utf-8")
