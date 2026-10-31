# Egrit-Preflight

Free, open-source ARM64 container preflight checks for NVIDIA Jetson and edge AI development.

**Status: version 0.1.0.** The CLI works and is tested, including real linux/arm64 container runs in CI. It has never
run on a Jetson and cannot verify one: see [what it cannot verify](docs/limitations.md) and
[what has been verified](docs/verification.md). Its security review was done by an AI reviewer, not a person; a human
review is welcome.

Egrit-Preflight tells you, on an ordinary Linux or macOS computer, whether you can run `linux/arm64` containers,
what an image declares about its architecture and Jetson dependencies, and whether a small CPU-only ARM64 smoke
test runs. It orchestrates Docker, Buildx and QEMU that you already have. It is not an emulator and it does not
install anything.

## What it cannot verify

A pass here is **not** a Jetson pass. ARM64 user-space emulation (or a native ARM64 run) does not provide the Jetson GPU,
the NVIDIA driver, the device nodes or the host-provided CUDA/TensorRT libraries. Those checks always come out as
`REQUIRES_HARDWARE` and need a physical Jetson. See [docs/limitations.md](docs/limitations.md).

## Install

Needs Python 3.9 or later and no other Python packages.

```sh
git clone <this repository>
cd egrit-preflight
python3 -m venv .venv && . .venv/bin/activate
pip install .
egrit-preflight --version
```

You also need Docker (Docker Engine on Linux, Docker Desktop on macOS). Setup: [Linux](docs/linux.md),
[macOS](docs/macos.md), [troubleshooting](docs/troubleshooting.md).

## Quickstart

```sh
egrit-preflight doctor                        # can this machine run linux/arm64 containers?
egrit-preflight image --image IMAGE_REF       # inspect an image; nothing is pulled or run
egrit-preflight smoke --image IMAGE_REF --yes # run one CPU-only ARM64 test (explicit consent)
egrit-preflight report --json --image IMAGE_REF --smoke --yes -o report.json
```

Use an immutable reference, and keep the tag beside the digest (`name:tag@sha256:<digest>`): the digest fixes the
content, and an L4T release stated in the tag can then still be compared with a target record. To find the digest
of a tag:

```sh
docker buildx imagetools inspect ubuntu:24.04     # the top-level "Digest:" line
egrit-preflight smoke --image ubuntu@sha256:<digest> --pull --yes
```

Expected: `[PASS] smoke.arch: linux/arm64 container ran the 'arch' test (prints 'aarch64').`, then
`[REQUIRES_HARDWARE] jetson.gpu` with the reminder that this is not GPU compatibility.

Where this fits in a build-to-device process, what to do with each outcome, and how to use it in CI:
[docs/where-it-fits.md](docs/where-it-fits.md).
The report's fields and the guarantees a program reading it can rely on: [docs/report-contract.md](docs/report-contract.md).
What `image` establishes about an NVIDIA L4T image from its registry, and what it does not, with a real run:
[docs/l4t-example.md](docs/l4t-example.md).
The same kind of run with `--target` set, showing what a target record adds: [docs/target-example.md](docs/target-example.md).
Optional and separate, not publicly released yet: Egrit's developer client, which can help an AI assistant choose one
of this repository's target records and keep your reports with a local plan; nothing here needs it. See
[docs/where-it-fits.md](docs/where-it-fits.md#optional-egrit-alongside-preflight).

## Outcomes and exit codes

| Outcome | Meaning |
|---|---|
| `PASS` | Checked and met. The `evidence` field says `observed` (this tool saw it) or `declared` (somebody said so). |
| `FAIL` | Checked and not met, or a refusal such as an unpinned tag. |
| `UNKNOWN` | Could not be established. Never treated as a pass. |
| `REQUIRES_HARDWARE` | Cannot be decided without a physical Jetson. |

Exit codes: `0` no FAIL, `1` at least one FAIL, `2` usage error or consent not given, `3` with `--strict`, no FAIL but
some UNKNOWN, `4` internal error (the tool itself failed: there is no result, and it is not a failed check), `130`
interrupted.

## Commands

- `doctor`: host OS/architecture, Docker CLI, daemon, Buildx and the ARM64 route: Linux x86_64 with QEMU, native Linux
  ARM64, Intel Mac with Docker Desktop emulation, Apple Silicon (ARM64 containers in Docker's VM). Read-only. If QEMU
  is missing it prints the manual recipe and runs nothing.
- `image --image REF [--target FILE] [--require-digest]`: reads a local image, or the registry manifest and its image config, without
  pulling or running it. Reports digest, architecture and the CUDA/TensorRT/L4T versions the image declares, and
  compares them with an optional target record. It also lists the SBOM and build-provenance attestations the registry
  publishes for the `linux/arm64` image (`image.sbom`, `image.provenance`, and `image.provenance` in the report). Missing
  data is `UNKNOWN`. A listed attestation is the publisher's declaration: its contents and any signature are **not**
  verified. Registry lookups read manifests only, never layers.
- `smoke --image REF --yes [--test arch|os-release|python-import] [--module NAME] [--pull] [--timeout S]`: one
  allowlisted command in a locked-down container ([security](docs/security.md)). `python-import --module numpy` checks
  that the image's `python3` imports a module on ARM64 CPU (no network, no GPU). Refuses an unpinned tag unless
  `--allow-mutable`.
- `report [--image REF] [--smoke --yes] [--json] [-o FILE]`: the above as one JSON document
  ([schema](schema/report.schema.json), [example](docs/example-report.json)). Set `SOURCE_DATE_EPOCH` for byte-identical
  output.

### Target record

`--target` reads a small JSON file. The fields used are `architecture`, `software.jetpack`, `software.jetson_linux`,
`runtimes.cuda`, `runtimes.tensorrt` and `status` (`declared` until read from a device). A version that is absent or
`"not established"` gives `UNKNOWN`. An `architecture` other than `aarch64` or `arm64` gives `target.architecture`
`FAIL`, because the report is about linux/arm64 only; an absent one adds no check. Versions you copy from NVIDIA release notes are declarations; the tool does not
embed a JetPack compatibility table, because one it cannot keep verified would be worse than none.

[examples/targets/](examples/targets/README.md) holds a declared record for each recent JetPack release (6.2.1, 6.2,
6.1 and 5.1.8), each citing NVIDIA's release page and the date it was read. Pass the one your device runs, for example
`--target examples/targets/jetpack-6.2.json`, and check it against what the device reports.

## Free and open source

Egrit-Preflight is Apache-2.0 and copyright 2026 Neul Space Ltd (see [NOTICE](NOTICE)). The local CLI needs no account, no login, no subscription and no usage credits, and it
sends no telemetry: it makes no network connections of its own (Docker may, when you ask it to pull or inspect a
registry). Functionality released in the free edition will not be withdrawn to create paid tiers.

Egrit may in future offer separate, optional services such as hardware-backed verification, managed testing, evidence
retention and deployment automation. None is part of this tool, and nothing here depends on them.

## Trademarks

NVIDIA, Jetson, JetPack, CUDA and TensorRT are trademarks or registered trademarks of NVIDIA Corporation. Docker is a
trademark of Docker, Inc. Egrit-Preflight is an independent project. It is not affiliated with, endorsed by or
sponsored by NVIDIA or Docker, and nothing it reports is an NVIDIA certification or a statement by NVIDIA. The names are
used only to say which software and hardware a check is about.

## What has been verified

See [docs/verification.md](docs/verification.md) for exactly what has run, where, and what has not.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
```

Contributing: [CONTRIBUTING.md](CONTRIBUTING.md). Security: [SECURITY.md](SECURITY.md).
