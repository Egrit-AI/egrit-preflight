"""Parity probe: do the two other readers of a Preflight report agree with the reference reader on accept or reject?

Report only. It imports, by path and only if present, Egrit-elevator's `bench/elevator_bench/preflight_intake.py`
(`parse`) and Egrit's `clients/python/src/egrit/preflight.py` (`parse_report`), feeds each the same 500 generated
documents the PF-1 generator makes (a valid fixture with 0 to 3 edits), and lists the disagreements. Nothing in those
repositories is changed. A disagreement is a finding for the owner of that reader, not a defect of this one.

Run: PYTHONPATH=src python3 assurance/preflight/parity.py [--count 500] [--show 5]
"""

import argparse
import importlib.util
import os
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hypothesis import given, settings  # noqa: E402

import assurance.preflight  # noqa: E402,F401
from assurance.preflight import generators as gen  # noqa: E402
from egrit_preflight import contract  # noqa: E402

# Sibling checkouts, by default next to this repository; override with EGRIT_ELEVATOR_DIR and EGRIT_DIR.
_ELEVATOR = Path(os.environ.get("EGRIT_ELEVATOR_DIR", Path(__file__).resolve().parents[2].parent / "Egrit-elevator"))
_EGRIT = Path(os.environ.get("EGRIT_DIR", Path(__file__).resolve().parents[2].parent / "Egrit"))
OTHER_READERS = {
    "elevator": (_ELEVATOR / "bench/elevator_bench/preflight_intake.py", "parse", "IntakeError"),
    "egrit-client": (_EGRIT / "clients/python/src/egrit/preflight.py", "parse_report", "PreflightError"),
}


def load_by_path(name, path):
    spec = importlib.util.spec_from_file_location(f"parity_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate(count):
    items = []

    @settings(max_examples=count, database=None, derandomize=True, deadline=None)
    @given(gen.edited_reports())
    def collect(item):
        items.append(item)

    collect()
    return items[:count]


def verdict(func, error_name, module, raw):
    try:
        func(raw)
        return "accept"
    except Exception as exc:
        if type(exc).__name__ == error_name:
            return f"reject {getattr(exc, 'code', '')}".strip()
        return f"raised {type(exc).__name__}: {exc}"[:120]


def reference_verdict(raw):
    try:
        doc, problems = contract.load_report(raw)
    except Exception as exc:
        return f"raised {type(exc).__name__}"
    return "accept" if doc is not None else "reject"


def describe(item):
    return item.fixture + " with " + (", ".join(f"{e.kind} at {'.'.join(map(str, e.path))} = {e.value!r}"[:90]
                                               for e in item.edits) or "no edits")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--show", type=int, default=5)
    args = parser.parse_args()
    readers = {}
    for name, (path, func, error) in OTHER_READERS.items():
        if path.exists():
            module = load_by_path(name, path)
            readers[name] = (getattr(module, func), error, module)
        else:
            print(f"{name}: not present at {path}, skipped")
    if not readers:
        print("no other reader present; nothing to compare")
        return 0
    items = generate(args.count)
    print(f"{len(items)} generated documents")
    for name, (func, error, module) in readers.items():
        disagreements = []
        crashes = []
        accepts_more = rejects_more = 0
        for item in items:
            raw = json.dumps(item.doc, ensure_ascii=False).encode("utf-8")
            ref = reference_verdict(raw)
            other = verdict(func, error, module, raw)
            if other.startswith("raised"):
                crashes.append((item, other))
            if (ref == "accept") != (other == "accept"):
                disagreements.append((item, ref, other))
                if other == "accept":
                    accepts_more += 1
                else:
                    rejects_more += 1
        print(f"\n{name}: {len(disagreements)} disagreements on {len(items)} documents "
              f"({accepts_more} accepted that the reference rejects, {rejects_more} rejected that the reference "
              f"accepts), {len(crashes)} raised something other than {error}")
        ordered = sorted(disagreements, key=lambda d: d[2] != "accept")  # accepted-by-other first: it matters most
        for item, ref, other in ordered[:args.show]:
            print(f"  reference {ref}, {name} {other}: {describe(item)}")
        for item, other in crashes[:args.show]:
            print(f"  {name} {other}: {describe(item)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
