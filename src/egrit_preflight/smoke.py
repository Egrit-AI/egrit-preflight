"""smoke: one explicitly requested, CPU-only linux/arm64 container run with a fixed, allowlisted test command.

The image's own entrypoint is replaced by the test command, so the only program started is the one named here.
This limits what Egrit-Preflight itself asks the image to do. It does not make an untrusted image safe to run.
"""

import re
import uuid

from . import outcomes as o
from . import safe
from .image import DIGEST_RE, valid_reference
from .runner import run as default_run

MODULE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")
# The module name is passed as an argument, never spliced into the code string.
IMPORT_CODE = "import importlib,sys; importlib.import_module(sys.argv[1]); print('imported', sys.argv[1])"

# name -> (argv run inside the image, check on stdout given the module, expectation). "{module}" is replaced.
TESTS = {
    "arch": (["uname", "-m"], lambda out, m: out.strip() == "aarch64", "prints 'aarch64'"),
    "os-release": (["cat", "/etc/os-release"], lambda out, m: "ID=" in out, "contains an ID= line"),
    "python-import": (["python3", "-I", "-B", "-c", IMPORT_CODE, "{module}"],
                      lambda out, m: out.strip() == f"imported {m}", "python3 imports the named module"),
}
DEFAULT_TEST = "arch"
PLATFORM = "linux/arm64"
LIMITS = {"memory": "512m", "cpus": "1", "pids": 128, "tmpfs_tmp": "16m"}
ISOLATION = [
    "no privileged mode, no added capabilities (all dropped), no-new-privileges",
    "no network (--network none), read-only root filesystem, 16 MB noexec /tmp",
    "every VOLUME the image declares is replaced by a 16 MB noexec tmpfs, so nothing is written to the host disk",
    "no host mounts, no device passthrough, no GPU; the plain runc runtime, NVIDIA_VISIBLE_DEVICES=void",
    "user 65534:65534, 512 MB memory, 1 CPU, 128 processes",
    "image entrypoint replaced by the test command",
    "wall-clock timeout: the container is force-removed on expiry, on Ctrl-C and on an internal error",
]
MAX_VOLUMES = 16
VOLUME_RE = re.compile(r"/[A-Za-z0-9._+/-]{1,200}")


def valid_module(module):
    return isinstance(module, str) and len(module) <= 100 and bool(MODULE_RE.fullmatch(module))


def build_run_argv(ref, test, name, module=None, volumes=()):
    argv_in_image = [module if a == "{module}" else a for a in TESTS[test][0]]
    tmpfs = f"rw,noexec,nosuid,size={LIMITS['tmpfs_tmp']}"
    return ["docker", "run", "--rm", "--name", name, "--label", "egrit-preflight=1",
            "--platform", PLATFORM, "--pull", "never",
            # A daemon whose default runtime is nvidia would honour NVIDIA_VISIBLE_DEVICES from the image's own env.
            "--runtime", "runc", "-e", "NVIDIA_VISIBLE_DEVICES=void",
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", str(LIMITS["pids"]), "--memory", LIMITS["memory"], "--memory-swap", LIMITS["memory"],
            "--cpus", LIMITS["cpus"], "--user", "65534:65534",
            "--tmpfs", f"/tmp:{tmpfs}",
            # --read-only does not cover anonymous volumes created from the image's VOLUME instruction.
            *[a for v in volumes for a in ("--tmpfs", f"{v}:{tmpfs}")],
            "--entrypoint", argv_in_image[0], ref, *argv_in_image[1:]]


def declared_volumes(ref, runner):
    """The VOLUME paths the image declares, as (paths, None); or (None, check-ready reason) if they cannot be read."""
    out = None
    for extra in (["--platform", PLATFORM], []):
        r = runner(["docker", "image", "inspect", *extra, "--format", "{{json .Config.Volumes}}", ref], 30)
        if r.returncode == 0:
            out = r
            break
        last = r
    if out is None:
        missing = re.search(r"No such image|not found", last.stderr, re.I)
        return None, ("missing" if missing else "unreadable")
    text = out.stdout.strip()
    if text in ("", "null"):  # Docker prints null when the image declares no volumes
        return [], None
    data = safe.loads(text)  # anything else that does not parse is unknown, never "no volumes"
    if not isinstance(data, dict) or len(data) > MAX_VOLUMES:
        return None, "unreadable"
    paths = []
    for v in data:
        if not (isinstance(v, str) and VOLUME_RE.fullmatch(v) and ".." not in v.split("/")):
            return None, "unreadable"
        if v.rstrip("/") not in ("/tmp", ""):  # /tmp is already a tmpfs; a duplicate mount point is an error
            paths.append(v.rstrip("/"))
    return sorted(set(paths)), None


def run_smoke(ref, test=DEFAULT_TEST, timeout=60.0, pull=False, allow_mutable=False, runner=default_run,
              name=None, module=None):
    checks = []
    res = {"reference": ref, "digest": None, "test": test, "platform": PLATFORM, "isolation": ISOLATION,
           "executed": False, "checks": checks}
    if not valid_reference(ref):
        checks.append(o.check("reference.valid", o.FAIL, "Not a valid image reference.", detail=repr(ref)[:120],
                              remediation="Use name[:tag][@sha256:<64 hex digits>]."))
        return res
    if test not in TESTS:
        checks.append(o.check("smoke.test", o.FAIL, f"Unknown test {test!r}.", detail=sorted(TESTS)))
        return res
    if test == "python-import" and not valid_module(module):
        checks.append(o.check("smoke.module", o.FAIL, "python-import needs a valid --module name.",
                              detail=repr(module)[:120],
                              remediation="Use a dotted Python module name such as numpy or os.path."))
        return res
    if module is not None:
        res["module"] = module
    m = DIGEST_RE.search(ref)
    res["digest"] = m.group(1) if m else None
    if not m and not allow_mutable:
        checks.append(o.check(
            "reference.pinned", o.FAIL, "Refusing to run a mutable tag: the result would not be reproducible.",
            remediation="Pin it: docker buildx imagetools inspect " + ref + " ; then use name@sha256:<digest>. "
                        "Or pass --allow-mutable to run anyway."))
        return res
    checks.append(o.check("reference.pinned", o.PASS if m else o.UNKNOWN,
                          "Reference is pinned by digest." if m else "Running a mutable tag (--allow-mutable).",
                          evidence=o.OBSERVED if m else o.NONE))

    if pull:
        p = runner(["docker", "pull", "--platform", PLATFORM, ref], 900)
        if p.returncode != 0:
            checks.append(_docker_failure(p, "image.pull"))
            return res
    cid = f"smoke.{test}"
    volumes, why = declared_volumes(ref, runner)
    if volumes is None:
        if why == "missing":
            checks.append(o.check(cid, o.UNKNOWN, "Image is not available locally, so nothing was run.",
                                  remediation=f"docker pull --platform {PLATFORM} {ref}   (or pass --pull)"))
        else:
            checks.append(o.check("smoke.volumes", o.UNKNOWN,
                                  "Could not read the image's declared volumes, so nothing was run: a writable image "
                                  "volume would not be bounded.",
                                  remediation="Run 'egrit-preflight doctor'; check that the image can be inspected."))
        return res
    res["volumes_replaced_by_tmpfs"] = volumes
    name = name or f"egrit-preflight-{uuid.uuid4().hex[:12]}"
    argv = build_run_argv(ref, test, name, module, volumes)
    try:
        r = runner(argv, timeout)
    except BaseException:
        _remove(runner, name)  # Ctrl-C or an internal error must not leave the container running
        raise
    res["executed"] = not r.not_found
    res["command"] = r.record()
    expect_desc = TESTS[test][2]

    failed = r.returncode != 0 and not r.timed_out  # image-controlled text only classifies a failed run
    if r.timed_out:
        gone = _remove(runner, name)
        checks.append(o.check(cid, o.FAIL, f"Timed out after {timeout:g}s; "
                              + ("container removed." if gone else f"the container may still be running: docker rm -f {name}"),
                              command=r.record(),
                              remediation="Emulated ARM64 is slow. Raise --timeout, or run on native ARM64."))
    elif failed and (r.not_found or "Cannot connect to the Docker daemon" in r.stderr or "docker.sock" in r.stderr):
        checks.append(_docker_failure(r, cid))
    elif failed and re.search(r"exec format error|no matching manifest|does not match the specified platform", r.stderr, re.I):
        checks.append(o.check(cid, o.FAIL, "This machine cannot run linux/arm64 containers (or the image has no "
                                           "arm64 variant).", detail=r.stderr.strip()[-300:], command=r.record(),
                              remediation="Run 'egrit-preflight doctor' for the setup steps."))
    elif failed and re.search(r"Unable to find image|No such image|pull access denied", r.stderr, re.I):
        checks.append(o.check(cid, o.UNKNOWN, "Image is not available locally, so nothing was run.",
                              detail=r.stderr.strip()[-300:], command=r.record(),
                              remediation=f"docker pull --platform {PLATFORM} {ref}   (or pass --pull)"))
    elif failed and re.search(r"executable file not found|no such file or directory", r.stderr, re.I):
        checks.append(o.check(cid, o.FAIL, f"'{TESTS[test][0][0]}' is not available in this image.",
                              detail=r.stderr.strip()[-300:], command=r.record(), evidence=o.OBSERVED))
    elif r.returncode != 0:
        checks.append(o.check(cid, o.FAIL, f"Test command exited with status {r.returncode}.",
                              detail=_tail(r.stderr), command=r.record(), evidence=o.OBSERVED))
    elif not TESTS[test][1](r.stdout, module):
        checks.append(o.check(cid, o.FAIL, f"Output did not meet the expectation ({expect_desc}).",
                              detail=r.stdout.strip()[-300:], command=r.record(), evidence=o.OBSERVED))
    else:
        checks.append(o.check(cid, o.PASS,
                              f"linux/arm64 container ran the '{test}' test ({expect_desc}{', ' + module if module else ''}).",
                              detail="The result is reported by the image's own binaries; only trust it for an image you trust.",
                              command=r.record(), evidence=o.OBSERVED))

    if res["digest"] is None and res["executed"]:
        d = runner(["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", ref], 15)
        if d.returncode == 0 and "@sha256:" in d.stdout:
            res["digest"] = d.stdout.strip().split("@")[1]
    checks.append(o.check(
        "jetson.gpu", o.REQUIRES_HARDWARE,
        "A passing ARM64 CPU test is not evidence of NVIDIA CUDA, TensorRT or Jetson GPU compatibility.",
        detail="No GPU, device node or NVIDIA runtime was used."))
    return res


def _remove(runner, name):
    """Force-remove the container, once more if the first attempt fails. True if it is gone (or never existed)."""
    for _ in range(2):
        try:
            r = runner(["docker", "rm", "-f", name], 30)
        except Exception:
            continue
        if r.returncode == 0 or re.search(r"No such container", r.stderr, re.I):
            return True
    return False


def _tail(text, lines=3, limit=300):
    """The last few non-blank lines: a traceback's useful part is its end, not its last 300 characters."""
    kept = [ln for ln in (text or "").splitlines() if ln.strip() and set(ln.strip()) - set("^~")]
    return "\n".join(kept[-lines:])[-limit:]


def _docker_failure(r, cid):
    detail = (r.stderr or "").strip()[-300:]
    if r.not_found:
        return o.check(cid, o.FAIL, "Docker CLI not found.", detail=detail,
                       remediation="Install Docker: https://docs.docker.com/get-docker/")
    return o.check(cid, o.FAIL, "Docker could not complete the request.", detail=detail, command=r.record(),
                   remediation="Run 'egrit-preflight doctor' to see what is missing.")
