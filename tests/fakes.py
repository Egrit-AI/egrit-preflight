"""A scripted stand-in for the subprocess runner. Mocked results are never hardware verification."""

import json

from egrit_preflight.runner import CmdResult

DIGEST = "sha256:" + "a" * 64
INFO_X86 = json.dumps({"ServerVersion": "27.0.1", "Architecture": "x86_64", "OSType": "linux",
                       "OperatingSystem": "Ubuntu 24.04"})
INFO_ARM = json.dumps({"ServerVersion": "27.0.1", "Architecture": "aarch64", "OSType": "linux",
                       "OperatingSystem": "Docker Desktop"})


class FakeRunner:
    """rules: list of (argv-prefix tuple, CmdResult-or-callable). First matching rule wins; calls are recorded."""

    def __init__(self, rules):
        self.rules, self.calls = rules, []

    def __call__(self, argv, timeout=30.0):
        self.calls.append(list(argv))
        for prefix, result in self.rules:
            if tuple(argv[:len(prefix)]) == tuple(prefix):
                res = result(argv) if callable(result) else result
                return CmdResult(list(argv), res.returncode, res.stdout, res.stderr, res.timed_out, 0.01,
                                 res.not_found)
        return CmdResult(list(argv), 1, "", "unscripted command")


def ok(stdout="", stderr=""):
    return CmdResult([], 0, stdout, stderr)


def bad(stderr="error", code=1, stdout=""):
    return CmdResult([], code, stdout, stderr)


def docker_ok(info=INFO_X86):
    return [(("docker", "--version"), ok("Docker version 27.0.1, build abc\n")),
            (("docker", "info"), ok(info)),
            (("docker", "buildx", "version"), ok("github.com/docker/buildx v0.15.1 abc\n"))]


def image_inspect(arch="arm64", env=None, repo_digest=None):
    return json.dumps([{"Architecture": arch, "RepoDigests": [f"x@{repo_digest}"] if repo_digest else [],
                        "Config": {"Env": env or [], "Labels": {"org.opencontainers.image.version": "1"}}}])


def inspect_rule(default=None, volumes="null", digest_line=None):
    """docker image inspect: answers the volumes query, the RepoDigests query, and anything else with `default`."""
    def answer(argv):
        if "{{json .Config.Volumes}}" in argv:
            return ok(volumes + "\n")
        if "--format" in argv:
            return ok(digest_line or f"ubuntu@{DIGEST}\n")
        return default if default is not None else bad("No such image")
    return (("docker", "image", "inspect"), answer)
