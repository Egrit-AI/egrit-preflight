# The report contract (schema version 1)

Last updated: 2026-10-30 (rule 11: a report has checks and a `jetson.gpu` check, #45) · 2026-10-30 (rule 2: `jetson.gpu` evidence is `none`, #44) · 2026-10-28 (rule 10, #32).

`egrit-preflight report --json` prints one JSON document. This page says what a program that reads it may rely on, and
what it must not assume. It is for CI scripts, dashboards and importers, whoever writes them. Nothing here needs an
account or a network: the contract is a schema, a reference reader and a set of fixtures that live in this repository.

| | |
|---|---|
| Schema | [`schema/report.schema.json`](../schema/report.schema.json) (JSON Schema 2020-12) |
| Reference reader | [`src/egrit_preflight/contract.py`](../src/egrit_preflight/contract.py) (standard library only) |
| Fixtures | [`tests/fixtures/reports/`](../tests/fixtures/reports/): 6 valid, 30 invalid |
| Example | [`docs/example-report.json`](example-report.json), a real run |

## What a report says, and what it does not

A report is a record of checks made **on the machine that ran the tool**, plus what an image or a registry *declares*.
It is not a statement about a Jetson, a GPU, CUDA or TensorRT.

- `hardware_verified` is **always `false`**. No report from this tool is a device result, whatever `overall` says.
- `overall` can be `PASS` while `requires_hardware` is not empty. A `PASS` is "nothing that this tool can check failed
  or is unknown", never "ready to deploy".
- `REQUIRES_HARDWARE` is **never a pass**. It means the question cannot be answered without a physical Jetson.
- A listed SBOM or provenance attestation is the publisher's declaration, whether it is a BuildKit attestation
  manifest or a digest-named tag (`REPO:sha256-<hex>.sbom`, the sigstore convention NVIDIA's images use).
  `image.provenance.signature_verified` is **always `false`**: nothing is verified, and the attestations' contents are
  not read.
- An `observed` check was observed by this tool on this host, emulated or native ARM64. It was never observed on a
  Jetson.

## Reading a report: fail closed

A reader should do these in order and reject the whole report at the first failure. Nothing is partly accepted.

1. Refuse input larger than 1 MiB (a real report is 4 to 15 KB).
2. Parse strict JSON. Refuse `NaN`, `Infinity`, invalid UTF-8 and very deep nesting.
3. Read `schema_version`. If it is not one you support (today: `"1"`), reject. Do not guess.
4. Validate against the schema, then apply the rules below that a schema cannot express.
5. Ignore properties you do not know. Never turn an unknown `outcome` or `evidence` value into `PASS`: reject it.
6. Keep the original `id`, `outcome` and `evidence` of every check. Do not re-grade.

`egrit_preflight.contract.load_report(data)` does all of this and returns `(document, problems)`.

## Fields

| Field | Meaning |
|---|---|
| `schema_version` | `"1"`. Changes only when a reader written for the old version could misread the new one. |
| `tool` | `name` is always `egrit-preflight`; `version` is the release that wrote the report. |
| `timestamp` | UTC, whole seconds, `2026-10-26T12:00:00Z`. When `SOURCE_DATE_EPOCH` is set (for reproducible output) it is that value, **not the clock**. It is when the tool says the report was made, not proof of when anything ran. |
| `hardware_verified` | Always `false`. See above. |
| `overall` | The worst check: `FAIL`, then `UNKNOWN`, then `PASS`. `REQUIRES_HARDWARE` does not change it. |
| `requires_hardware` | Ids of the checks whose outcome is `REQUIRES_HARDWARE`. Always includes `jetson.gpu`. |
| `host` | `os`, `architecture`, `execution_mode` (`linux-arm64-native`, `linux-x86_64-qemu`, `macos-apple-silicon-vm`, `macos-intel-docker-desktop-emulation`, `unsupported-host`; treat as an open set), `binfmt_qemu_aarch64`, `python`. |
| `docker` | CLI, daemon and Buildx versions, daemon architecture and OS. Parsed fields only; the raw output of `docker info` is never recorded. |
| `target` | `architecture` is always `linux/arm64`. `record` is the summary of the `--target` file, or `null`. Everything in it is **declared** by whoever wrote the file, whatever its own `status` says; checks that use it are graded `declared`. If the record states an `architecture`, the check `target.architecture` is `PASS` (`declared`) for `aarch64` or `arm64` and `FAIL` (`declared`) for anything else: the report is about linux/arm64 only. |
| `image` | `null` if no image was given. Else `reference` (what you typed), `digest`, `architecture`, `platforms`, `provenance`. |
| `image.digest` | `null`, or `sha256:` plus 64 hex digits, taken from the reference, from the local image's repo digests, or computed over the manifest document the registry served for a tag. It identifies that; it does not prove which image a smoke test ran unless the reference was pinned (`smoke` refuses an unpinned tag unless told otherwise). |
| `checks` | The results. See below. |
| `uncertainties` | The checks that are `UNKNOWN` or `REQUIRES_HARDWARE`, listed once per id and outcome (so `jetson.gpu` appears once, not once per section). |
| `limitations` | Fixed sentences about what the tool cannot verify. Text for people. |
| `provenance` | `smoke_executed` says whether a container was started. `generated_by`, `python` and `inputs` (the image reference and the SHA-256 of the target file) say how it was made. `telemetry` is a sentence saying that none is sent. |
| `commands` | The command lines run and their bounded output. Text for people. |

### A check

| Field | Meaning |
|---|---|
| `id` | Stable name, for example `image.architecture`. New ids can appear in later releases; keep unknown ones and their outcome. |
| `section` | `doctor`, `image` or `smoke`. |
| `outcome` | `PASS`, `FAIL`, `UNKNOWN` or `REQUIRES_HARDWARE`. Exactly these four. |
| `evidence` | `observed`, `declared` or `none`. |
| `summary` | One sentence for a person. |
| `detail`, `remediation`, `command` | Optional. Free text or data from the machine, the image or a registry. See the allowlist. |

The same check id can appear in more than one section: `jetson.gpu` appears once in each section that ran, by design.
Use `section` and `id` together when you need to tell them apart.

## Rules every report obeys

`check_report` enforces these, and a fixture breaks each one:

1. `hardware_verified` is `false`.
2. Every `jetson.gpu` check is `REQUIRES_HARDWARE` with `evidence` `none`: nothing about the GPU is observed or
   declared by this tool.
3. `requires_hardware` lists exactly the ids of the `REQUIRES_HARDWARE` checks.
4. `overall` is what the checks give (`FAIL` over `UNKNOWN` over `PASS`).
5. A check whose id starts `target.` or `runtime.` is never `observed`: it compares declared values.
6. `image.sbom` and `image.provenance` are never `PASS` unless `declared`.
7. `image.provenance.signature_verified` is `false`.
8. `image.digest` is `null` or a full `sha256:` digest. `timestamp` has the shape above.
9. `target.architecture` is `linux/arm64`. The schema already required this; the reference reader now checks it too.
10. Every entry of `uncertainties` is an object with a valid `id`, a `section`, a `summary` and an `outcome` of
    `UNKNOWN` or `REQUIRES_HARDWARE`, and the entries list each `UNKNOWN` and `REQUIRES_HARDWARE` check once per id
    and outcome, no more and no fewer. The schema requires only the four keys. An entry's `section` is the section
    the check was first seen in; it and `summary` are checked for shape, not against the check.
11. `checks` is not empty, it includes a `jetson.gpu` check, and `requires_hardware` includes `jetson.gpu`. A report
    that checked nothing, or left out the check it cannot run, never reads as a clean `PASS`.
12. The image names a registry controls and the allowlist below exports are short tokens: `image.architecture` is
    `null` or 1 to 32 of `a-z0-9_-`; each `image.platforms` entry is `os/architecture[/variant]` of such tokens; each
    attestation's `predicate_types` entry is 1 to 200 printable ASCII characters without spaces. A report with an
    escape sequence, a bidi override or an oversized value there is rejected.

## What a consumer may import

The free-text parts of a report come from the machine, the image or a registry: error messages, command lines, command
output, image labels and environment values. They help a person reading the report. They are **not** safe to import
or upload automatically, and nothing in this tool or its documentation says published report contents are safe to send
anywhere. The tool already keeps secrets out of what it records (see [security.md](security.md)), but a path, a user
name or a message from your own machine can still appear in `detail` or `command`.

A consumer should import only this allowlist and drop everything else:

- `schema_version`, `tool.name`, `tool.version`, `timestamp`, `hardware_verified`, `overall`, `requires_hardware`
- `host.os`, `host.architecture`, `host.execution_mode`
- `docker.cli_version`, `docker.daemon_version`, `docker.buildx_version`, `docker.daemon_architecture`
- `target.architecture` and, from `target.record`, only `jetpack`, `jetson_linux` and `status`
- `image.reference`, `image.digest`, `image.architecture`, `image.platforms`, and from `image.provenance`: `status`,
  `signature_verified`, and each attestation's `predicate_types` and `subject_digest`
- for each check: `id`, `section`, `outcome`, `evidence`, `summary`; for each uncertainty: the same minus `evidence`
- `provenance.smoke_executed`

`contract.allowlisted_view(report)` returns exactly this and refuses an invalid report. The registry-controlled names in
it are checked by rule 12. `image.reference` is text you typed and `summary` is generated from checks, so a consumer
should still escape both when showing them.

## Changing the contract

Within `schema_version` `"1"` only **additive** changes are made: a new optional property, a new check id, new text in
`detail`, a new string in an open set such as `execution_mode`. A reader that ignores what it does not know keeps
working.

Anything else is **breaking** and needs `schema_version` `"2"`: removing or renaming a property, changing what a
property or a value means, adding a value to `outcome`, `evidence`, `section`, `overall` or `provenance.status` (readers
reject unknown values on purpose), making an optional property required, or ever loosening `hardware_verified` or
`signature_verified`. When version 2 exists, the version 1 schema and fixtures stay in the repository.

Targets other than linux/arm64 are not added to this report. How they could be handled without changing version 1 is
in [target-neutral-design.md](target-neutral-design.md).

Every pull request that touches `report.py`, `contract.py`, `schema/` or the fixtures must:

1. run `python3 -m tests.make_fixtures` and include the fixture changes (the tests fail if they are stale; a version
   bump changes `tool.version` in them, so it needs this too);
2. say in its description whether the change is additive or breaking;
3. add a line under "Report contract" in `CHANGELOG.md`.

Before a release, the maintainers run any known consumer's own tests against the new fixtures. That check is manual and
belongs to the consumer: this repository's CI depends on no other repository and no hosted service.

## For consumers: using the fixtures

Copy `tests/fixtures/reports/` (Apache-2.0, like the rest) into your tests. Every file in `valid/` must be accepted.
Every file in `invalid/` must be rejected as a whole, and the file name says why (`unsupported-version`,
`hardware-verified-true`, `gpu-check-pass`, `overall-pass-over-a-fail`, `signature-verified-true`,
`target-architecture-not-arm64`, and so on). The fixtures are real output of the tool run against a scripted Docker
with a fixed clock; the hosts, versions and digests are made up.

Twelve of the invalid fixtures (`gpu-check-pass`, `gpu-check-observed`, `checks-empty`, `gpu-check-missing`,
`requires-hardware-without-gpu`, `requires-hardware-emptied`, `overall-pass-over-a-fail`,
`declared-claimed-observed`, `sbom-claimed-observed`, `uncertainty-outcome-verified`, `uncertainties-emptied`,
`architecture-control-chars`) are
accepted by the schema alone, because the rules behind them
cannot be written in JSON Schema. A consumer that validates against the schema only will accept them: apply the rules
above as well.

## For maintainers: checking the schema

CI validates the schema and every fixture with a small checker in `tests/` and needs no extra package. When the schema
changes, also run the real validator once:

```sh
python3 -m venv /tmp/jsv && /tmp/jsv/bin/pip install jsonschema
/tmp/jsv/bin/python -c "
import json, glob
from jsonschema import Draft202012Validator as V
s = json.load(open('schema/report.schema.json')); V.check_schema(s); v = V(s)
for f in glob.glob('tests/fixtures/reports/valid/*.json') + ['docs/example-report.json']:
    assert not list(v.iter_errors(json.load(open(f)))), f
"
```
