# Design note: targets other than an ARM64 Jetson

Last updated: 2026-10-28. Status: **decided for now.** Follow-ups 1 and 2 are done; follow-up 3 (a separate target
assessment) is design only. Nothing here changes the report schema. It records how Egrit-Preflight would grow towards other targets (an x86-64 CPU host, a Jetson described in more
detail, other accelerators) without weakening what a schema version 1 report means today.

## The decision

1. **The ARM64 report stays exactly as it is.** `schema_version` stays `"1"`, `target.architecture` stays
   `linux/arm64`, `hardware_verified` stays `false`, and every rule in [report-contract.md](report-contract.md) holds.
   No report that is valid today becomes invalid, and no report that is invalid today becomes valid.
2. **An ARM64 `PASS` is never evidence about any other target.** It is not an x86-64 result, and it is not a Jetson GPU,
   CUDA or TensorRT result. A consumer that shows a version 1 report next to another target must say so.
3. **No generic target is added to the version 1 report**, not even as an optional property. The reasons are below.
4. **If a consumer needs to compare a workload with other targets, that is a separate document**, a target assessment
   with its own name and its own version, not a new version of this report. It is built only when a consumer states the
   need in an issue here, with the fields it would import. Until then it exists only as the sketch in this note and in
   [`tests/fixtures/targets/`](../tests/fixtures/targets/).
5. **Two small fixes inside version 1 come first** (see "Follow-up"). Both make the tool stricter about what it already
   promises; neither changes the schema. Both are done.

## What version 1 assumes about the target

An inventory of the places where "the target is a linux/arm64 Jetson" is built in.

| Where | What it fixes |
|---|---|
| `schema/report.schema.json` | `target.architecture` is the constant `linux/arm64`; `hardware_verified` is the constant `false`; `schema_version` is the constant `"1"`. |
| Contract rule 2, `check_report` | Every `jetson.gpu` check is `REQUIRES_HARDWARE`. |
| Contract, fields table | `requires_hardware` always includes `jetson.gpu`. `REQUIRES_HARDWARE` means "needs a physical Jetson". |
| Contract rule 5 | `target.*` and `runtime.*` checks compare declared values and are never `observed`. |
| `doctor` | `arm64.execution` asks whether this host can run linux/arm64 containers; `execution_mode` and `binfmt_qemu_aarch64` describe that route. |
| `image` | `image.architecture` passes only for an `arm64` image. `target.jetpack`, `target.l4t`, `runtime.cuda`, `runtime.tensorrt` read a JetPack-shaped record. |
| `smoke` | `smoke.arch` expects `aarch64`. |
| Consumer allowlist | `target.record` gives only `jetpack`, `jetson_linux` and `status`. |
| Fixtures | All 6 valid fixtures are linux/arm64 reports with `hardware_verified: false`. |

A consumer that follows the contract reads the allowlisted view, rejects any `schema_version` but `"1"`, rejects unknown
`outcome` and `evidence` values, and ignores unknown properties. Nothing in this note asks such a consumer to change.

## Options compared

| | A. Additive change to version 1 | B. Report `schema_version` 2 | C. Separate target assessment |
|---|---|---|---|
| What it is | New optional fields, such as a second target architecture | The same report, made target-neutral | A new document type beside the report |
| Existing consumers | Keep working only if the new fields do not change what old ones mean | Must upgrade, or reject every new report | Unaffected; they never see it |
| Risk of misreading | **High**: an old reader ignores the new field and still reads `overall: PASS` as the whole answer | Low once upgraded | Low: the document says which target it is about |
| Cost | Small to write, permanent to explain | Every consumer, every fixture, a migration | One new schema and reader, only when needed |
| Verdict | **Rejected** | **Rejected for now** | **Chosen, when a consumer needs it** |

Why A is rejected: the meaning of `overall`, `REQUIRES_HARDWARE` and `jetson.gpu` is tied to linux/arm64 and a Jetson.
Letting the target vary changes what those values mean, and the contract counts a change of meaning as breaking, even
when the field names stay the same. Allowing any value but `linux/arm64` in `target.architecture` is breaking for the
same reason. An optional field that an old reader ignores is exactly the failure this note is meant to prevent: the old
reader would still show `PASS`.

Why B is rejected for now: it would make every consumer upgrade to keep reading the ARM64 report they read today, for a
need nobody has stated yet. If it ever happens, the version 1 schema and fixtures stay in the repository, as the
contract already says.

Why C: the ARM64 report keeps its meaning, a consumer that wants other targets opts in, and the new document can state
from the start that an ARM64 result does not carry over.

## Two synthetic targets

Both are in [`tests/fixtures/targets/`](../tests/fixtures/targets/), are `declared`, and were not read from any machine.

**An x86-64 CPU host** (`x86-64-cpu.declared.json`). Given to `--target`, the tool still produces a linux/arm64
report: `target.architecture` is `linux/arm64`, `image.architecture` says the image provides linux/arm64, and the JetPack
and L4T checks are `UNKNOWN` because the record states neither. Since follow-up 2, the record's own
`architecture: "x86_64"` gives a `target.architecture` check that is `FAIL`, graded `declared`, saying the report is
about linux/arm64 only, so `overall` is `FAIL`. Nothing in the report claims anything about x86-64.

**A declared Jetson** (`jetson.declared.json`). Every version is `"not established"`, so `target.jetpack`, `target.l4t`,
`runtime.cuda` and `runtime.tensorrt` are all `UNKNOWN`, `target.architecture` (`aarch64`) is `PASS` graded
`declared`, `jetson.gpu` is `REQUIRES_HARDWARE` in each section, `overall`
is `UNKNOWN` and `hardware_verified` is `false`. That is the behaviour this note wants everywhere: a missing fact stays
missing.

The two `assessment-sketch.*.json` files show what option C could say about the same targets. They are design only. They
carry no `schema_version`, so a version 1 reader rejects them, and it still rejects them if someone adds
`schema_version: "1"`. In the sketches:

- the target is always `declared`, and `hardware_verified` is `false`;
- `arm64_report.applies_to_target` is `no` for the x86-64 host and `cpu-user-space-only` for the Jetson, never `yes`;
- no check is `observed` and none is `PASS`, because nothing was run against these targets;
- an accelerator check (`accelerator.gpu`) is always `REQUIRES_HARDWARE`.

The sketches reuse the four outcomes and three evidence grades on purpose. A real assessment schema would be designed
in its own issue; these files fix only the rules above.

`tests/test_target_neutral_design.py` checks all of this offline, with a scripted Docker and no hardware.

## Follow-up

Smallest first, owned by this repository's maintainers and run with the usual command. 1 and 2 are done, in one pull
request.

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
```

1. **Reference reader parity. Done.** `check_report` did not check `target.architecture`, although the schema fixes it
   to `linux/arm64`, so a reader that used only `check_report` would accept a report that says `linux/amd64`. It now
   rejects that (contract rule 9), the invalid fixture `target-architecture-not-arm64.json` breaks it, and
   `CHANGELOG.md` says so under "Report contract". Every report the schema accepts is still accepted, so this is not a
   breaking change. The known-gap test is replaced by
   `test_the_reference_reader_rejects_any_target_architecture_but_linux_arm64`.
2. **Refuse a target record for another architecture. Done.** When a `--target` record states an `architecture` that
   is not `aarch64` or `arm64` (any case), a `target.architecture` check is `FAIL`, graded `declared`, saying the report
   is about linux/arm64 only. When it states `aarch64` or `arm64`, the check is `PASS`, graded `declared`. When it
   states nothing (absent, or `"not established"`), no check is added, so such records give the same result as before.
   A new check id is additive, and rule 5 already covers `target.*`. The fixtures are regenerated, and the known-gap
   test is replaced by `test_an_x86_description_is_refused_with_a_declared_fail` and
   `test_an_arm64_description_passes_as_declared_and_an_absent_one_adds_no_check`.
3. **A separate target assessment.** Only when a consumer asks for it in an issue here, with the fields it would import
   and how it keeps them out of the version 1 path. Its own schema, reader and fixtures; the version 1 report is not
   touched.

Before a release that includes 1 or 2, the maintainers run known consumers' own tests against the new fixtures, as the
contract already asks. That check belongs to each consumer.

## What stays as it is

- The free, standalone CLI: no account, no telemetry, no network connections of its own.
- The consumer allowlist. Nothing in this note adds a field a consumer may import.
- This note does not replace or reshape the ARM64 CLI, add an evaluator framework, run anything on hardware, or claim
  any hardware result. See [limitations.md](limitations.md).
