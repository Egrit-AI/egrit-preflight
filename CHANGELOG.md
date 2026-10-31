# Changelog

Issue and pull request numbers in entries up to the public release of 2026-10-30 refer to the private development
repository; entries after it refer to this repository.

## Unreleased

- Docs: `docs/target-example.md` records one real `image` run with `--target examples/target-orin-nano-jetpack-6.2.json`
  against `dustynv/l4t-pytorch:r36.4.0`, pinned as `name:tag@sha256:<digest>`, on 2026-10-31: `target.architecture`,
  `target.jetpack` and `target.l4t` PASS (declared), `runtime.cuda` and `runtime.tensorrt` UNKNOWN because the image
  declares no versions. It explains why keeping the tag beside the digest is what lets `target.l4t` be compared. The
  report is `docs/example-target-report.json`, and `tests/test_contract.py` now checks it against the contract (#22).
- `image` and `smoke`: the `reference.pinned` remediation now says `name:tag@sha256:<digest>` instead of
  `name@sha256:<digest>`, and `--image` help and the README say the same. The L4T release is read from the tag when the
  image does not set `L4T_VERSION`, so advice that dropped the tag also dropped the `target.l4t` comparison. Text only;
  no outcome changes. The `mutable-tag.json` fixture is regenerated (#22).

## 0.1.0 (2026-10-30)

First release. Standard library only, Python 3.9 or later, Apache-2.0.

- Security review of 2026-10-30 (the code changed since the review of 2026-10-26), all findings fixed:
  - Report contract (additive, `schema_version` stays 1): new rule 12. `image.architecture`, `image.platforms` and
    attestation `predicate_types` come from a registry and are exported by the allowlist, so the reference reader now
    requires them to be short tokens; before, an escape sequence or a 3000-character architecture in a registry config
    was accepted and exported. One new invalid fixture, `architecture-control-chars.json` (6 valid, 30 invalid).
  - `image`: an architecture, platform part or label key that is not a short token is not copied (it reads as not
    established); at most 32 labels are kept. Digest-named tags are probed only when the image itself was found, so a
    missing image no longer gets `image.sbom` PASS from a `.sbom` tag, and an unreachable registry costs no extra
    timeouts.
  - Reports are written as ASCII JSON, so C1 controls and bidi overrides are escaped, as `docs/security.md` said.
  - Release workflow: the job that can write runs no build code; the build backend is pinned
    (`.github/release-constraints.txt`); a tag that is not on `main` is refused.
  - `docs/security.md` now describes the image config read and the tag probes.
- Examples: `examples/targets/` holds a declared target record for JetPack 6.2.1, 6.2, 6.1 and 5.1.8, each with the
  Jetson Linux, CUDA and TensorRT versions from NVIDIA's release page and the date it was read (2026-10-30). The
  folder README indexes them and says how to add a release. `examples/target-orin-nano-jetpack-6.2.json` keeps its
  values and now cites the 6.2 page instead of "not re-checked". The no-target `remediation` points at the library
  (text only; no outcome changes). `tests/test_examples.py` checks every record loads, cites an NVIDIA page with a
  date, compares cleanly against an arm64 image and is indexed (#10).
- Docs: `docs/l4t-example.md` records one real `image` run against `nvcr.io/nvidia/l4t-jetpack` pinned by digest,
  from the `L4T inspect` workflow on 2026-10-30: architecture PASS from the config, SBOM PASS from the digest-named
  tag, nothing pulled, `jetson.gpu` REQUIRES_HARDWARE. It states what a registry read does not establish. The report
  is `docs/example-l4t-report.json`; `docs/verification.md` records the run (#2, public repository).
- CI: a manually triggered `L4T inspect` job (`workflow_dispatch`) inspects one digest-pinned NVIDIA L4T image from
  its registry on an Ubuntu runner, which has the Docker and network the development sandbox lacked. It pulls and
  runs nothing, asserts only what must hold off-device (`jetson.gpu` REQUIRES_HARDWARE, `hardware_verified` false,
  the digest read equals the one given) and uploads the `image` output and the JSON report as the evidence for the
  documented example (#2, public repository).
- Report contract (additive, `schema_version` stays 1): `image` UNKNOWNs say what to supply. The four checks that run
  without a target record carry a `remediation` naming `--target` and the example record. When the image was read
  only from its registry manifest, `runtime.cuda`, `runtime.tensorrt` and `target.l4t` say the version was not read
  there (declared dependencies come from a local image only) and give the `docker pull --platform linux/arm64`
  command, instead of "Image declares no CUDA version" from a path that never read the image. Text and
  `remediation` only: no new check id, no outcome changes. Fixtures regenerated (#9, public repository).
- `image`: for a single-platform registry manifest (NVIDIA's L4T images), the image config is now read with
  `docker buildx imagetools inspect --format '{{json .Image}}'`, a small JSON document and not a layer, so
  `image.architecture` is PASS or FAIL (observed) and the declared CUDA, TensorRT and L4T versions are reported as
  the local path reports them. When the config cannot be read, `image.architecture` stays UNKNOWN with its
  remediation. Nothing is pulled; `jetson.gpu` stays REQUIRES_HARDWARE. Not yet run against a real registry
  (`docs/verification.md`) (#7, public repository).
- `image`: SBOM, attestation, signature and VEX artefacts published as digest-named tags (`REPO:sha256-<hex>.sbom`
  and so on, the sigstore convention NVIDIA's l4t images use) are now found when no BuildKit attestation manifest is
  listed. Their manifests are read, never their contents. A `.sbom` tag makes `image.sbom` PASS (`declared`); a
  `.att` tag is named in `image.provenance`, which stays UNKNOWN because its predicate type is not read; a `.sig` tag
  is recorded with `signature_verified` still `false`. `image.provenance.status` keeps its existing values; the found
  tags are recorded under a new, additive `image.provenance.tag_artifacts`. Images with neither style are unchanged
  (#8, public repository).
- Report contract (additive, `schema_version` stays 1): new rule 11. The reference reader rejects a report whose
  `checks` is empty, one with no `jetson.gpu` check, and one whose `requires_hardware` leaves out `jetson.gpu`. Before,
  `checks: []` with `overall: PASS` was accepted: a report that checked nothing read as a clean pass. A
  `requires_hardware` without `jetson.gpu` was already rejected by rule 3 whenever the check is present; the new rule
  gives it a clearer message. Three new
  invalid fixtures, `checks-empty.json`, `gpu-check-missing.json` and `requires-hardware-without-gpu.json` (6 valid,
  29 invalid); the schema alone accepts all three. Every report the tool writes is still accepted (#45, from #33
  rule 2).
- Report contract (additive, `schema_version` stays 1): rule 2 now also requires every `jetson.gpu` check to carry
  `evidence: "none"`, the only value the writer emits. Before, a `jetson.gpu` check marked `observed` or `declared`
  was accepted and could read as GPU evidence. One new invalid fixture, `gpu-check-observed.json` (6 valid, 26
  invalid); the schema alone accepts it. Every report the tool writes is still accepted (#44, from #33 rule 1).
- Report contract (additive, `schema_version` stays 1): `load_report` no longer raises `UnicodeEncodeError` on text
  holding a lone surrogate; it returns `(None, ["report is not valid UTF-8 text"])`, as for any other unreadable
  input. Bytes input was already unaffected, and no valid report is affected. The PF-2 generator now includes such
  text (#39, found by the independent review of #37).
- Report contract (additive, `schema_version` stays 1): new rule 10. Additive in the sense the earlier rules 2 to 6
  are: the reference reader is tightened beyond the schema and nothing the writer emits changes. The reference reader `check_report` now validates each
  `uncertainties` entry (an object with a valid `id`, a `section`, a `summary`, and an `outcome` of `UNKNOWN` or
  `REQUIRES_HARDWARE`) and requires the entries to list each `UNKNOWN` and `REQUIRES_HARDWARE` check once per id and
  outcome. Before, any entry was accepted and `allowlisted_view` exported its `outcome`, so a word such as `VERIFIED`
  reached a consumer. Two new invalid fixtures, `uncertainty-outcome-verified.json` and `uncertainties-emptied.json`
  (6 valid, 25 invalid); both pass the schema alone, which requires only the four keys. Every report the tool writes
  is still accepted; a hand-made report whose `uncertainties` disagree with its checks is now rejected (#32, found by
  the PF-4 property check).
- Report contract (additive, `schema_version` stays 1): the reference reader `check_report`, and so `load_report`, no
  longer raises `TypeError` on a check whose `outcome` is a list or object, or on a `requires_hardware` holding a
  non-string; both now return a rejection (`outcome must be one of ...`, `requires_hardware must be an array of
  strings`), as rules 1 to 5 of "Reading a report" promise. Two new invalid fixtures, `outcome-not-a-string.json` and
  `requires-hardware-not-strings.json` (6 valid, 23 invalid). The schema already rejected both shapes, so no report
  the schema accepts is rejected (#31, found by the PF-2 property check).
- Docs: [design note](docs/target-neutral-design.md) on targets other than an ARM64 Jetson. Report `schema_version` 1
  is unchanged and an ARM64 `PASS` is never read as an x86-64 or Jetson GPU result. Synthetic x86-64 CPU and Jetson
  target descriptions in `tests/fixtures/targets/`, tested offline. No change to the tool or the report.
- `image` and `report`: a `--target` record's `architecture` is now compared. Anything but `aarch64` or `arm64` gives a
  new check `target.architecture`, `FAIL` graded `declared`, because the report is about linux/arm64 only; `aarch64`
  or `arm64` gives `PASS` graded `declared`; an absent architecture adds no check.
- Report contract (additive, `schema_version` stays 1): new check id `target.architecture`. The reference reader
  `check_report` now rejects a `target.architecture` other than `linux/arm64`, which the schema already required (rule
  9), with a new invalid fixture `target-architecture-not-arm64.json` (6 valid, 21 invalid). No report the schema
  accepts is rejected.
- Release workflow: pushing a `v*` tag builds the wheel and sdist, checks the tag against `__version__` and
  that `docs/releases/<tag>.md` exists, and publishes a GitHub release carrying both and those notes.
  `docs/releases/v0.1.0.md` states what the release cannot verify. `CONTRIBUTING.md` gains the release
  procedure (#6, public repository).

Prepared on 2026-10-26 in the private development repository and not tagged then; everything above was added before
the first tag.

- `doctor`: host, Docker, Buildx and the ARM64 route (Linux x86_64 with QEMU, native Linux ARM64, Intel Mac emulation,
  Apple Silicon). Read-only; never registers QEMU for you.
- `image`: architecture, digest, declared CUDA/TensorRT/L4T versions and SBOM/provenance attestations the registry lists,
  compared with an optional target record. Reads manifests only; missing data is `UNKNOWN`.
- `smoke`: one allowlisted CPU-only linux/arm64 test (`arch`, `os-release`, `python-import`) in a locked-down container,
  only with `--yes`, only for a digest-pinned image unless told otherwise.
- `report`: one JSON document with a schema; reproducible under `SOURCE_DATE_EPOCH`.
- Outcomes are `PASS`, `FAIL`, `UNKNOWN` and `REQUIRES_HARDWARE`. A passing ARM64 test is never reported as CUDA,
  TensorRT or Jetson GPU compatibility.
- No account, no telemetry, no network connections of its own.
- Report contract (`schema_version` 1): documented in [docs/report-contract.md](docs/report-contract.md), with a stricter
  schema, a reference reader (`egrit_preflight.contract`), a consumer allowlist, 6 valid and 20 invalid fixtures, and a
  compatibility policy. The report gains `hardware_verified`, always `false`, so a `PASS` in `overall` cannot be read as a
  device result.

Security: an independent AI review found twelve issues (raw `docker info` in reports, writable image volumes, unbounded
output capture, terminal escape sequences, crashes on malformed input, among others). All are fixed and tested; see
[docs/security.md](docs/security.md).

Not verified: any real Jetson; Docker Desktop on macOS; rootless Docker; a daemon whose default runtime is `nvidia`;
any NVIDIA image. Not on PyPI yet: install from source.
