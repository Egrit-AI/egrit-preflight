# What has been verified

Last updated: 2026-11-12. Version 0.1.0. The CI record below is for `f1887df` (2026-10-30). 0.1.0 also includes the
changes merged after it; CI passed on `main` at `b413118` after them (run 56, 2026-11-11,
https://github.com/Egrit-AI/egrit-preflight/actions/runs/43120631615), and the Release workflow runs the unit tests
and a clean install again on the tagged commit.

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

## Verified against a live NVIDIA registry (GitHub Actions, `L4T inspect`, 2026-10-30)

Run https://github.com/Egrit-AI/egrit-preflight/actions/runs/41063039600 on `ubuntu-latest` (x86_64, Docker 29.4.2,
Buildx 0.38.1), against `nvcr.io/nvidia/l4t-jetpack@sha256:34ccf0f3b63c6da9eee45f2e79de9bf7fdf3beda9abfd72bbf285ae9d40bb673`,
anonymously, nothing pulled or run:

- The single-platform manifest's image config was read with `imagetools inspect --format '{{json .Image}}'`:
  `image.manifest` PASS, `image.architecture` PASS (observed, `arm64`). The scripted shape the unit tests assume
  matched the real one.
- The digest-named `.sbom` tag was found: `image.sbom` PASS (declared); a `.sig` tag was recorded, `signature_verified`
  false; `image.provenance` UNKNOWN (no attestation bundle). Contents were not read.
- `jetson.gpu` REQUIRES_HARDWARE, `hardware_verified` false, `smoke_executed` false, digest read equal to the one given.
- The config's environment declares no CUDA, TensorRT or L4T version, so the version comparisons stay UNKNOWN without a
  target record. The written example is [l4t-example.md](l4t-example.md); the report is
  [example-l4t-report.json](example-l4t-report.json).

## Verified with a target record against Docker Hub (cloud container, 2026-10-31)

`image --target examples/target-orin-nano-jetpack-6.2.json` against
`dustynv/l4t-pytorch:r36.4.0@sha256:a05c85def9139c21014546451d3baab44052d7cabe854d937f163390bfd5201b`, a community
image, read from its registry with no Docker daemon running and nothing pulled:

- `target.architecture`, `target.jetpack` and `target.l4t` PASS (declared); `target.l4t` agrees at major.minor
  (image r36.4.0 from the tag, target 36.4.3).
- `runtime.cuda` and `runtime.tensorrt` UNKNOWN: the image's environment declares no CUDA or TensorRT version.
- The same image pinned by digest alone gives `target.l4t` UNKNOWN, because the L4T release is read from the tag.
- Not checked: an NVIDIA `nvcr.io` image with a target record (the container's proxy refused `nvcr.io`), and any
  CUDA or TensorRT comparison. The written example is [target-example.md](target-example.md); the report is
  [example-target-report.json](example-target-report.json).

## Reported from an Apple Silicon Mac with Docker Desktop (contributor, 2026-10-31)

A contributor ([sa3301](https://github.com/sa3301)) ran the README quickstart on an Apple Silicon Mac and posted the
outputs on [issue #5](https://github.com/Egrit-AI/egrit-preflight/issues/5#issuecomment-6546163700). The maintainers did
not run this and have not reproduced it; the files are the contributor's, not ours.

Host: macOS 26.5.2, Docker Desktop 4.97.0 (Docker 29.9.2, Buildx 0.38.1), Python 3.14.6, `egrit-preflight` 0.1.0.

- `doctor`: `arm64.execution` PASS with mode `macos-apple-silicon-vm` (linux/arm64 containers run in Docker's Linux
  VM, without x86 emulation); `jetson.gpu` REQUIRES_HARDWARE; overall PASS.
- `smoke` against `ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852`, pulled with
  `--pull`: `smoke.arch` PASS (the container printed `aarch64`); `jetson.gpu` REQUIRES_HARDWARE.
- `report` with that pinned image, `--smoke --pull --yes`: smoke ran (`smoke_executed` true); overall UNKNOWN, from the
  expected `jetson.gpu`, target and provenance items. The same command with the unpinned `ubuntu:24.04` refused to run
  the smoke test and gave overall FAIL (`reference.pinned`), which is how the README example's missing `--pull` and
  pinning were found.
- Not checked: an Intel Mac (none was available to the contributor), and anything on a Jetson. Docker Desktop on
  Windows or Linux is also not verified.

## Verified by CI (GitHub Actions, run 27 on `main` at `f1887df`, 2026-10-30)

All 15 jobs passed: https://github.com/Egrit-AI/egrit-preflight/actions/runs/41140016572. `f1887df` is the last code
change before v0.1.0; the commit the tag points at adds only this record. The first full run, run 3 at `fb579c7` on
2026-10-26 (10 jobs), was in the private development repository and is not public.

- Unit tests on Ubuntu 24.04 and macOS (`macos-latest`), Python 3.9, 3.10, 3.11, 3.12 and 3.13.
- Clean install (build, install the wheel in a fresh venv, run the CLI) on Ubuntu and macOS.
- **Real linux/arm64 container execution**, twice: x86_64 Linux with QEMU, and a native arm64 runner
  (`ubuntu-24.04-arm`). Each pins `ubuntu:24.04` to its digest at run time, runs `smoke`, and asserts `smoke.arch` is
  PASS, stdout is `aarch64` and `jetson.gpu` is `REQUIRES_HARDWARE`. The reports are uploaded as artifacts.
- The optional `assurance` job (PF-1 to PF-4: property-based, exhaustive and mutation checks of the report reader).
- The first run found one CI configuration fault, not a code fault: `ubuntu-latest` moved to a release without a
  Python 3.9 build. The unit matrix is pinned to `ubuntu-24.04`.

## Not verified

- Docker Desktop on an Intel Mac, Windows or Linux, and any Docker Desktop run by the maintainers (the macOS runners
  run the unit and install jobs only, without Docker; one Apple Silicon run is reported above, by a contributor),
  rootless Docker, remote Docker contexts (the QEMU check reads the local machine).
- Any L4T behaviour and everything on a Jetson: CUDA, TensorRT, GPU, device nodes, performance. These are
  `REQUIRES_HARDWARE`. The registry read of one L4T image is verified (above); nothing from that image has run anywhere.
- Install from PyPI: nothing is published to PyPI.
