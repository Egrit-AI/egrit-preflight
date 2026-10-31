"""Command line. Exit codes: 0 no FAIL; 1 at least one FAIL; 2 usage error or consent not given;
3 (only with --strict) no FAIL but UNKNOWN present; 4 internal error (the tool failed, there is no result);
130 interrupted."""

import argparse
import math
import os
import sys

from . import __version__, report as reportmod, safe, smoke as smokemod
from . import outcomes as o
from .doctor import run_doctor
from .image import inspect_image
from .smoke import DEFAULT_TEST, TESTS, run_smoke

MARK = {o.PASS: "PASS", o.FAIL: "FAIL", o.UNKNOWN: "UNKNOWN", o.REQUIRES_HARDWARE: "REQUIRES_HARDWARE"}


def _human(title, checks, out):
    """Terminal output. Text that came from a container or a registry is scrubbed of control characters first."""
    print(safe.clean(title), file=out)
    for c in checks:
        print(safe.clean(f"  [{MARK[c['outcome']]}] {c['id']}: {c['summary']}"), file=out)
        if c.get("detail") and isinstance(c["detail"], str):
            print(safe.clean(f"      {c['detail']}"), file=out)
        if c.get("remediation"):
            for line in c["remediation"].splitlines():
                print(safe.clean(f"      -> {line}"), file=out)
    print(f"Overall: {o.overall(checks)}", file=out)


def _seconds(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number")
    if not math.isfinite(value) or not 1 <= value <= 3600:
        raise argparse.ArgumentTypeError("must be between 1 and 3600 seconds")
    return value


def _exit(checks, strict):
    outcomes = {c["outcome"] for c in checks}
    if o.FAIL in outcomes:
        return 1
    if strict and o.UNKNOWN in outcomes:
        return 3
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="egrit-preflight",
        description="Free, open-source ARM64 container preflight checks for NVIDIA Jetson and edge AI development. "
                    "Local only: no account, no telemetry. A pass here is not Jetson, CUDA or TensorRT compatibility.")
    p.add_argument("--version", action="version", version=f"egrit-preflight {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="{doctor,image,smoke,report}")

    def common(sp, image_required=False):
        sp.add_argument("--json", action="store_true", help="print the machine-readable report")
        sp.add_argument("--strict", action="store_true", help="exit 3 if any check is UNKNOWN")

    d = sub.add_parser("doctor", help="check Docker, Buildx and ARM64 execution support (read-only)")
    common(d)

    i = sub.add_parser("image", help="inspect an image reference (nothing is pulled or run)")
    i.add_argument("--image", required=True, help="image reference, ideally name:tag@sha256:<digest>")
    i.add_argument("--target", help="target record JSON with JetPack / L4T / CUDA versions")
    i.add_argument("--require-digest", action="store_true", help="treat a mutable tag as FAIL, not UNKNOWN")
    common(i)

    s = sub.add_parser("smoke", help="run one CPU-only linux/arm64 container test (needs --yes)")
    s.add_argument("--image", required=True, help="image reference, ideally name:tag@sha256:<digest>")
    s.add_argument("--test", default=DEFAULT_TEST, choices=sorted(TESTS), help="allowlisted test (default: arch)")
    s.add_argument("--module", help="module name for --test python-import (no network, no GPU)")
    s.add_argument("--timeout", type=_seconds, default=60.0, help="seconds before the container is removed (default 60)")
    s.add_argument("--pull", action="store_true", help="allow 'docker pull --platform linux/arm64' of the image first")
    s.add_argument("--allow-mutable", action="store_true", help="run a tag that is not pinned by digest")
    s.add_argument("--yes", action="store_true", help="consent to running this image's code in a container")
    common(s)

    r = sub.add_parser("report", help="doctor (+ image, + smoke) as one report")
    r.add_argument("--image")
    r.add_argument("--target")
    r.add_argument("--require-digest", action="store_true")
    r.add_argument("--smoke", action="store_true", help="also run the smoke test (needs --image and --yes)")
    r.add_argument("--test", default=DEFAULT_TEST, choices=sorted(TESTS))
    r.add_argument("--module", help="module name for --test python-import")
    r.add_argument("--timeout", type=_seconds, default=60.0)
    r.add_argument("--pull", action="store_true")
    r.add_argument("--allow-mutable", action="store_true")
    r.add_argument("--yes", action="store_true")
    r.add_argument("-o", "--output", help="write the report to this file instead of stdout")
    common(r)
    return p


def _consent_refusal(args, err):
    print("Refusing to run: smoke executes code from the image inside a container.\n"
          "Containers isolate processes; they are not a security boundary against a hostile image. "
          "Only test images you trust.\nIt would run (with --network none, read-only, all capabilities dropped, "
          "no mounts, no GPU):\n  " + " ".join(smokemod.build_run_argv(args.image, args.test, "NAME", args.module or "MODULE")) +
          "\nRe-run with --yes to consent.", file=err)
    return 2


def main(argv=None, out=None, err=None, **hooks):
    """hooks (runner=...) let tests replace the subprocess runner."""
    out, err = out or sys.stdout, err or sys.stderr
    args = build_parser().parse_args(argv)
    try:
        return _run(args, out, err, hooks)
    except KeyboardInterrupt:
        print("egrit-preflight: interrupted", file=err)
        return 130
    except Exception as exc:
        # A crash must not look like a failed check (exit 1). Set EGRIT_PREFLIGHT_DEBUG=1 for the traceback.
        if os.environ.get("EGRIT_PREFLIGHT_DEBUG"):
            raise
        print(f"egrit-preflight: internal error ({type(exc).__name__}); no result was produced. "
              "Please report it with the command you ran. EGRIT_PREFLIGHT_DEBUG=1 shows the traceback.", file=err)
        return 4


def _run(args, out, err, hooks):
    runner = hooks.get("runner")
    kw = {"runner": runner} if runner else {}

    if args.command == "doctor":
        doc = run_doctor(**kw)
        if args.json:
            out.write(reportmod.dumps(reportmod.build_report(doc)))
        else:
            _human("Host: {os}/{architecture}; ARM64 mode: ".format(**doc["host"]) + doc["arm64_execution_mode"],
                   doc["checks"], out)
        return _exit(doc["checks"], args.strict)

    if args.command == "image":
        img = inspect_image(args.image, args.target, args.require_digest, **kw)
        checks = img["checks"]
        if args.json:
            out.write(reportmod.dumps(reportmod.build_report(run_doctor(**kw), image=img, target_path=args.target)))
        else:
            _human(f"Image: {args.image}  digest: {img['digest'] or 'unknown'}", checks, out)
        return _exit(checks, args.strict)

    if args.command == "smoke":
        if not args.yes:
            return _consent_refusal(args, err)
        sm = run_smoke(args.image, args.test, args.timeout, args.pull, args.allow_mutable, module=args.module, **kw)
        if args.json:
            out.write(reportmod.dumps(reportmod.build_report(run_doctor(**kw), smoke=sm)))
        else:
            _human(f"Smoke ({sm['platform']}, test: {args.test}) digest: {sm['digest'] or 'unknown'}",
                   sm["checks"], out)
        return _exit(sm["checks"], args.strict)

    # report
    if args.smoke and not (args.image and args.yes):
        print("report --smoke needs --image and --yes (consent to run the image).", file=err)
        return 2
    if args.output:
        problem = safe.output_path_problem(args.output)
        if problem:
            print(f"egrit-preflight: cannot write the report: {safe.clean(problem)}", file=err)
            return 2
    doc = run_doctor(**kw)
    img = inspect_image(args.image, args.target, args.require_digest, **kw) if args.image else None
    sm = run_smoke(args.image, args.test, args.timeout, args.pull, args.allow_mutable, module=args.module, **kw) if args.smoke else None
    rep = reportmod.build_report(doc, img, sm, args.target)
    text = reportmod.dumps(rep)
    if args.output:
        try:
            safe.write_private(args.output, text)
        except OSError as exc:
            print(f"egrit-preflight: cannot write the report: {safe.clean(exc)}", file=err)
            out.write(text)  # the run is not lost
            return 2
    if args.json or not args.output:
        out.write(text)
    else:
        _human("Report written to " + args.output, rep["checks"], out)
    return _exit(rep["checks"], args.strict)
