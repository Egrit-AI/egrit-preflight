# Vendor target profile: the companion record and its input contract

Last updated: 2026-11-18. Status: `profile_version` `"1"`, with a reference reader and fixtures. **No CLI command reads
a profile.** `--target` still takes the small target record, the report stays schema version 1 and
`hardware_verified` stays `false`. The research behind this record is in
[vendor-target-profile-design.md](vendor-target-profile-design.md).

## What it is for

A commercial edge computer built on a Jetson module may run a vendor's own Linux, one particular JetPack and BSP
combination and a vendor-managed container environment. A product family name does not say which. A vendor target
profile describes **one identified hardware and software configuration** and keeps, for every technical fact, who said
it, where, when, and about which revision.

It is a record of statements. It is not a report, not a compatibility table and not a result from a device.

| Piece | Where |
|---|---|
| Schema | [`schema/vendor-target-profile.schema.json`](../schema/vendor-target-profile.schema.json) |
| Reference reader | `egrit_preflight.profile` (standard library only, no network call) |
| Fixtures | [`tests/fixtures/profiles/`](../tests/fixtures/profiles/), all synthetic |
| Tests | `tests/test_profile.py`, offline, with a scripted Docker |

## The record

```json
{
  "document": "egrit-preflight vendor target profile",
  "profile_version": "1",
  "identity": {
    "vendor": "Example Vendor (synthetic)",
    "product": "Edge One",
    "model": "E1-16",
    "module": "jetson-orin-nx-16gb",
    "hardware_revision": "B",
    "software_revision": "1.4.0",
    "profile_revision": "1"
  },
  "facts": {
    "jetpack": [
      {
        "value": "6.2",
        "evidence": "declared",
        "source_url": "https://vendor.example/edge-one/software-1.4.0",
        "retrieved": "2026-11-18",
        "applies_to": {"hardware_revision": "B", "software_revision": "1.4.0"}
      }
    ]
  },
  "required_interfaces": ["csi-camera", "gpu"]
}
```

The example is shortened: a real record lists all nine facts.

**`identity`** names one configuration. `vendor`, `product` and `profile_revision` are strings. `model`, `module`,
`hardware_revision` and `software_revision` are a string or `null`; all seven keys are always present, so a value that
is not established is written `null` and never left out. `module` (the compute module) is kept apart from the product
name. `software_revision` is the vendor's software or BSP revision. `profile_revision` changes whenever a statement is
added, removed or edited.

**`facts`** has exactly these nine keys: `architecture`, `os_distribution`, `os_build`, `abi`, `jetpack`,
`jetson_linux`, `cuda`, `tensorrt`, `container_runtime`. Each is a list of statements; an empty list means nothing is
stated. A statement has:

| Key | Meaning |
|---|---|
| `value` | The value exactly as the source writes it, or `null`. Never `"not established"` or a guess. |
| `evidence` | `declared` (somebody said so), `observed` (read from a device) or `none` (with a `null` value only). |
| `source_url` | An `https` URL. Required for `declared`; may be `null` for `observed`. |
| `retrieved` | `YYYY-MM-DD`: the day the source was read, or the day of the observation. Required with a value. |
| `applies_to` | The `hardware_revision` and `software_revision` the source is about; `null` where it names none. |

Every statement key is required, including `source_url` and `retrieved` when their values are `null`.
Equivalence statements also require explicit provenance keys; an observed equivalence may use `source_url: null`.

**`required_interfaces`** lists the device interfaces a workload needs (lower-case names such as `gpu`, `csi-camera`,
`can0`). **`equivalences`** is optional and described below. `synthetic: true` marks made-up test data.

Unknown top-level properties are ignored. An unknown key inside `facts` is refused, so a misspelt fact cannot pass as
"nothing stated".

## How it is read

The reader is fail closed: a record that is too large (over 1 MiB), not valid JSON, of another `profile_version`, or
that breaks any rule above is rejected whole (`load_profile`, `check_profile`). The rules that decide what a record
establishes:

1. **A statement counts only for the exact revisions the profile identifies.** Both `applies_to` revisions must equal
   the identity's, and a `null` revision matches nothing. A statement about another revision is set aside and counted,
   never merged. So a profile whose software revision is not established establishes no fact: a vendor page that says
   only "JetPack 6 compatible" is kept as a statement and gives no JetPack or Jetson Linux version.
2. **One distinct value is `stated`; none is `missing`; two or more are `contradictory`.** A contradiction keeps every
   source. Neither the newest document nor the first one listed is preferred, and near matches (`36.4` and `36.4.0`)
   are not merged.
3. **Nothing is inherited.** A custom operating system does not take an ABI, an Ubuntu base or a library set from its
   module name or its JetPack statement. Each fact stands on its own statements.
4. **Two configurations are equivalent only when every identity field is established and equal**, or when one carries
   an `equivalences` entry that names every identity field of the other, lists the facts it covers, and has a grade, a
   date and (when declared) a source. The entry covers only the listed facts and only that direction. A shared vendor,
   product family or module is never enough.
5. **`observed` changes no outcome here.** A version 1 report has no observed target check, so an export is always
   `declared`, and `hardware_verified` is `false` whatever the profile holds.

## What validation returns

`assess_profile` checks one profile against the linux/arm64 requirement. It uses the report's four outcome words but
is not a report and has no `overall`.

| Case | Check | Outcome |
|---|---|---|
| Model, module or a revision not established | `profile.identity.<key>` | `UNKNOWN` |
| A fact missing, or stated only for another revision | `profile.<fact>` | `UNKNOWN` |
| A fact contradicted | `profile.<fact>` | `UNKNOWN`, with every source in `detail` |
| Architecture stated and not ARM64 | `profile.architecture` | `FAIL`, graded `declared` |
| Architecture stated as `aarch64` or `arm64` | `profile.architecture` | `PASS`, graded `declared` |
| GPU, driver and container GPU runtime | `profile.gpu` | `REQUIRES_HARDWARE`, always |
| Each required interface | `profile.interface.<name>` | `REQUIRES_HARDWARE`, always |

The declared architecture is the only `PASS`, as in a version 1 report. Any other stated fact adds no check. The result
also carries `complete` (every fact stated once, identity established, no `FAIL`) and two constants,
`compatibility_established: false` and `hardware_verified: false`. `complete` means the record is fully and
consistently written. It does not mean an image will work on the device.

## The consumer and input contract

A program that reads a profile (an exporter, a catalogue, an assistant) must:

- read it with the rules above, or reject it; never use a `missing` or `contradictory` fact, or one set aside;
- never fill a `null` from another product, another revision, the newest vendor document or a generic JetPack record;
- show a contradiction with all of its sources;
- never present `complete`, or any export, as a compatibility or hardware result;
- keep profiles out of the report path: a profile is not a report and the report reader rejects one.

There is one route from a profile to the CLI. `to_target_record` writes the small record `--target` already reads:

- `architecture`, `software.jetpack`, `software.jetson_linux`, `runtimes.cuda` and `runtimes.tensorrt` are copied only
  when `stated`. Otherwise the version is `"not established"`, which the CLI reports as `UNKNOWN`, and a profile with no
  stated architecture exports none.
- `status` is always `declared`, including when every statement is `observed`.
- `sources` lists only the statements that were used.
- The profile's identity, ABI, operating system, container runtime and interfaces are **not** carried into a report.
  The CLI compares none of them, and nothing here may be described as if it did.

A profile passed to `--target` by mistake states no version the CLI recognises, so every target comparison is
`UNKNOWN`.

## What each kind of evidence can and cannot establish

| Source of the result | What it can establish | What it cannot |
|---|---|---|
| A vendor target profile | What a named source declares about one configuration | That the device has it installed, or that any image works on it |
| Registry manifest and image configuration (`image`) | What an image declares: architecture, labels, environment, tag | Anything about the device |
| ARM64 CPU user-space run (`smoke`) | That one allowlisted command ran in linux/arm64 user space | The device's ABI or libraries, GPU, CUDA or TensorRT at run time |
| A physical device (outside this tool) | Installed versions, GPU and driver, peripherals such as cameras, radios and buses, performance and power | Flight or production qualification, which needs its own process |

Peripheral, performance and flight verification are out of scope here. See [limitations.md](limitations.md).

## Compatibility

This record is new and separate, so it is additive: report schema version 1, the consumer allowlist, the CLI, every
existing fixture and every record in [`examples/targets/`](../examples/targets/README.md) are unchanged, and the
JetPack example records stay valid `--target` inputs. A reader rejects any `profile_version` it does not know. Within
`profile_version` `"1"` only additive changes are made; a change to what a statement, a state or an outcome means is a
new version.

## Fixtures

`python3 -m tests.make_profile_fixtures` rewrites [`tests/fixtures/profiles/`](../tests/fixtures/profiles/), and the
tests fail if the files differ from what it produces. Every profile is synthetic: the vendor, products, revisions and
versions are made up and the URLs use the reserved `.example` domain. No fixture describes a real product, and none
was read from a vendor page or a device.

## Not done

- No real vendor profile is shipped. The public pages read for the design note do not state a hardware revision, a
  software revision or exact versions, so an honest profile of those products would be `UNKNOWN` throughout.
- No CLI command or report field. Either needs its own issue, with the fields a consumer would import.
- No observed procedure. Reading versions from a physical device is separate work.
