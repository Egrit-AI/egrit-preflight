# Roadmap

Last updated: 2026-10-28. Four milestones, small issues, each with a measurable acceptance criterion. Status is the
state of the development version, not a promise of dates.

## M1: Packaging and Developer Experience
- [x] Installable with `pip install .`, stdlib only, console script `egrit-preflight`. *AC: clean venv install runs `--version` and `doctor` (done locally; CI job `clean-install`).*
- [x] Consistent commands, `--json`, exit codes 0/1/2/3. *AC: documented in README; covered by `tests/test_cli_report.py`.*
- [x] README, Linux, macOS, troubleshooting, limitations. *AC: each linked from README.*
- [ ] Publish to PyPI under a project-owned account. *AC: `pipx install egrit-preflight` works; needs maintainers' credentials, not automated here.*

## M2: ARM64 Execution
- [x] Docker, Buildx and daemon detection with remediation. *AC: tests for missing CLI, stopped daemon, missing Buildx.*
- [x] QEMU/binfmt detection, never installed automatically. *AC: test asserts `doctor` never runs `docker run`.*
- [x] Locked-down `smoke` with timeout, digest pinning, consent. *AC: tests assert the flag set; real run printed `aarch64`.*
- [ ] Run on native ARM64 and Apple Silicon. *AC: CI job `real ARM64 smoke (native arm64)` green (done, run 3); one macOS Docker Desktop manual run recorded in verification.md (open).*
- [x] Allowlisted `python-import` test that imports a named module inside the image. *AC: allowlist entry plus tests; no network, no GPU.*

## M3: Jetson Compatibility Evidence
- [x] Target record input (JetPack, Jetson Linux, CUDA, TensorRT), with `declared`/`observed` grading. *AC: tests for missing JetPack, L4T mismatch, unsupported CUDA.*
- [x] JSON report with schema and reproducible output. *AC: schema file; identical output under `SOURCE_DATE_EPOCH` with identical inputs.*
- [x] Record an image SBOM/provenance reference if the registry provides one. *AC: report field `image.provenance`, UNKNOWN when absent.*
- [ ] A clearly limited NVIDIA L4T user-space example. *AC: runs only if the reference is reachable and pinned; documents host-library limits; no GPU claim.*
- [x] Design note on targets other than an ARM64 Jetson, keeping report schema version 1 unchanged. *AC: [docs/target-neutral-design.md](target-neutral-design.md); synthetic x86-64 CPU and Jetson descriptions tested offline in `tests/test_target_neutral_design.py`.*
- [ ] Observed target records from a physical Jetson. *AC: `status: observed` record produced on a device; needs hardware.*

## M4: Public v0.1 Release
- [x] CI green on Linux and macOS across Python 3.9 to 3.13. *AC: matrix passes on `main`.*
- [x] At least one real ARM64 container execution in CI. *AC: `arm64-smoke` jobs pass and upload `report.json`.*
- [ ] Security review of command construction and report contents. *AC: second reviewer signs off; findings fixed or recorded.*
- [ ] Release artifacts: wheel and sdist built in CI, tag `v0.1.0`, release notes stating the limitations. *AC: artifacts attached; verification.md updated from CI.*
- [x] Branch protection on `main`: required CI checks, reviews. *AC: ruleset enabled.*

A stable `v0.1.0` is not tagged until the three gates in M4 (CI green, real ARM64 execution in CI, clean install in CI) pass.
Until then, versions are `0.1.0.devN` and say so.
