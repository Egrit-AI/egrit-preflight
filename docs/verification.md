# What has been verified

Last updated: 2026-10-30. Version 0.1.0. CI results below are for `fb579c7`.

## Verified by running it

On one x86_64 Linux machine (a cloud sandbox, Python 3.13, Docker Engine 29.9.2 with Buildx 0.38.1, QEMU 8.2.2
registered by hand through `/proc/sys/fs/binfmt_misc` with the `F` flag):

- 156 unit tests pass (`PYTHONPATH=src python3 -m unittest discover -s tests -t . -v`). They use scripted Docker output
  for the deterministic negative cases; they are not hardware or container verification.
- Clean installation: `pip install .` into a new virtual environment, then `egrit-preflight --version`, `doctor` and
  `image` run from outside the source tree. A wheel builds with `pip wheel`.
- `doctor` without QEMU reported `arm64.execution` FAIL with the manual recipe and changed nothing; with the handler
  registered it reported PASS.
- `smoke` without QEMU against a pinned, pulled `ubuntu` image reported FAIL (`exec format error`), as intended.
- **A real linux/arm64 container ran** under QEMU with the restricted flags in [security.md](security.md):
  `ubuntu@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac` (the digest the `ubuntu:24.04` tag
  resolved to on 2026-10-26), `uname -m` printed `aarch64`, and the `os-release` test passed. The report is
  [example-report.json](example-report.json). `image` against the registry reported `linux/arm64` present.
- `smoke --test python-import` ran for real on `python@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962`
  (`python:3.13-slim`, 2026-10-26, QEMU): `os.path` and `sqlite3` PASS, a missing module FAIL with the import error, an
  image without Python FAIL (`ubuntu`), an invalid module name rejected before any Docker call.
- `image` attestation listing, against the live registry on 2026-10-26: `python@sha256:d98cc29d…0962` lists an SPDX SBOM
  and SLSA v0.2 provenance for `linux/arm64` (both PASS, declared); `ubuntu@sha256:68ee2200…ff33ac` lists an SPDX SBOM only
  (provenance UNKNOWN). Attestation contents and signatures were not read or verified.
- Container isolation, against real Docker (2026-10-26, QEMU): an image declaring `VOLUME /data` let a container with the
  old flags write 300 MiB into that volume on the host disk (root filesystem read-only, as documented); with a 16 MiB
  tmpfs over the volume the same write stopped with "No space left on device". A flooding process made the old runner
  capture 382 MiB and peak at 1160 MiB resident in 4 seconds; the new runner keeps 1 MiB and peaked at 16 MiB. A
  1-second timeout removed the container; a real SIGINT exited 130 with no container left. `--runtime runc` was
  accepted. **Not tested:** a daemon with `nvidia` as its default runtime (none available), so the GPU-hiding flags are
  reasoned, not observed.
- The report contract (`docs/report-contract.md`), checked three ways: the unit tests run the schema, the reference reader
  and all 26 fixtures; the real `jsonschema` 4.26.0 package (Draft 2020-12, run by hand once, not in CI) confirmed the
  schema is well formed, accepts every valid fixture and the example report, and rejects every invalid fixture the schema
  can express; the five that need the extra rules are accepted by the schema alone, as the contract says. The documented
  commands are parsed against the real CLI by a test. No importer for any other product has been run against the fixtures.
- The real run exposed one defect (an index digest inspected locally names no architecture under Docker's containerd
  image store); it is fixed and has a regression test.

## Verified by CI (GitHub Actions, run 3 on `main` at `fb579c7`, 2026-10-26)

All 10 jobs passed: https://github.com/Egrit-AI/egrit-preflight/actions/runs/40331286519

- Unit tests on Ubuntu 24.04 and macOS (`macos-latest`), Python 3.9, 3.10, 3.11, 3.12 and 3.13 (3.10 and 3.12 added after this run; see the latest run on `main`).
- Clean install (build, install the wheel in a fresh venv, run the CLI) on Ubuntu and macOS.
- **Real linux/arm64 container execution**, twice: x86_64 Linux with QEMU, and a native arm64 runner
  (`ubuntu-24.04-arm`). Each pins `ubuntu:24.04` to its digest at run time, runs `smoke`, and asserts `smoke.arch` is
  PASS, stdout is `aarch64` and `jetson.gpu` is `REQUIRES_HARDWARE`. The reports are uploaded as artifacts.
- The first run found one CI configuration fault, not a code fault: `ubuntu-latest` moved to a release without a
  Python 3.9 build. The unit matrix is pinned to `ubuntu-24.04`.

## Not verified

- Docker Desktop on any platform (the macOS runners run the unit and install jobs only, without Docker), rootless
  Docker, remote Docker contexts (the QEMU check reads the local machine).
- Any NVIDIA image (the sandbox's network blocked `nvcr.io`), any L4T behaviour, and everything on a Jetson: CUDA,
  TensorRT, GPU, device nodes, performance. These are `REQUIRES_HARDWARE`.
  The `L4T inspect` workflow (`workflow_dispatch`, `.github/workflows/l4t-inspect.yml`) exists to make the registry
  read on a runner with Docker and network; no run of it is recorded here yet.
- Install from PyPI: nothing is published to PyPI.
- Reading the image config of a single-platform registry manifest (the NVIDIA L4T case) against a real registry: the
  path is unit-tested with scripted `docker buildx imagetools inspect --format '{{json .Image}}'` output only, and
  the exact shape of that output on a real Docker is to be confirmed.
- Digest-named tag artefacts (`.sbom`, `.sig`, `.att`, `.vex`) against a real registry: the probe is unit-tested with
  scripted output only. The access probe of 2026-10-29 saw such tags on `nvcr.io/nvidia/l4t-jetpack`, and no CLI run
  has read them yet.
