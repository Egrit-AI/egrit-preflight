# Versioned vendor target profiles: proposed companion record

Research for Preflight #33, 17 November 2026. Proposal only: no runtime, report schema, compatibility assertion or release changes.

Update, 18 November 2026: the companion record, its reference reader and synthetic fixtures for the matrix below are in [vendor-target-profile.md](vendor-target-profile.md). The CLI and report v1 are unchanged, and the sections below are kept as written on 17 November.

## Public evidence and limits

- [EDGX Sterna](https://www.edgx.space/product/sterna), retrieved 2026-11-17: the vendor describes an Orin NX 16GB system, custom Linux/Yocto and JetPack 6 compatibility. Grade: vendor declaration, not device observation. The page does not pin JetPack minor release, L4T/BSP build, CUDA/TensorRT, ABI, container-runtime version or installed system revision. Do not substitute a generic JetPack 6 target for this unknown configuration.
- [EDGX Morus](https://www.edgx.space/product/morus), retrieved 2026-11-17: the page describes orbital compute but does not establish a module, software stack or exact revision. Grade: vendor declaration with required technical fields unknown. Do not copy Sterna values into Morus.

Only public pages were used. Datasheet forms were not submitted. No private documents or hardware were accessed. Marketing performance and flight claims are not compatibility evidence.

## Recommendation

Extend the separate-document approach in [target-neutral-design.md](target-neutral-design.md), not the report. Start with a versioned companion record, not inferred compatibility rules. This is configuration evidence, not a second implemented assessment engine; an executable consumer/exporter needs its own explicit input contract and issue before implementation. Keep current `--target` inputs and report v1 unchanged. This is a design artifact until a parser, schema and tests are accepted; current CLI code must not be described as enforcing it.

Identify one configuration by vendor, product, model/variant, hardware revision, vendor software/BSP revision and profile revision. Keep exact module separate from product name. Each technical fact should carry value, evidence grade, source URL, retrieval/observation date and applicable configuration revision. Preserve conflicting sources rather than choosing the newest silently. Missing versions remain null.

Record OS distribution/build, architecture, ABI, JetPack, Jetson Linux/L4T, CUDA, TensorRT, container runtime and required interfaces independently. Custom OS must not inherit Ubuntu ABI or standard JetPack library assumptions solely from a Jetson module name. Different configurations are non-equivalent unless an explicit, attributable equivalence statement covers the compared fields.

A future accepted exporter may produce today's small target JSON from unambiguous declared fields. It must never mark status observed without device evidence or claim that current CLI compares profile identity or ABI. Even an input record marked observed is treated as declared by report v1 target checks. A companion file cannot extend report v1 guarantees by itself.

## Proposed validation matrix

| Case | Required future profile-validation outcome |
|---|---|
| Missing software revision | UNKNOWN; no inferred JetPack/L4T tuple |
| Contradictory declarations | UNKNOWN, retaining both sources |
| Sterna and Morus share vendor | Not equivalent; no inheritance |
| Different hardware/software revisions | Not equivalent without scoped evidence |
| Wrong architecture | FAIL against linux/arm64 requirement |
| ABI absent | UNKNOWN despite ARM64 user-space smoke |
| Unproven GPU/runtime interfaces | REQUIRES_HARDWARE |
| Existing JetPack examples | Remain valid under current CLI |

Fixtures must be synthetic and labelled, not purported observed vendor values. Keep future profile-parser tests separate from CLI contract fixtures. Merged #40 protects parsed tag/environment L4T conflicts on main; it does not implement this design and is absent from existing v0.1.0 assets.

## Acceptance still outstanding

Agree and implement companion schema and validation before calling this matrix tested. Re-run existing examples, report fixtures and full unit suite against implementation. Registry metadata establishes image declarations; ARM64 CPU execution establishes only the tested user-space command. Neither establishes installed GPU drivers, peripherals, performance or flight qualification. Report v1 hardware_verified remains false always, even if a companion contains device observations. Physical verification requires separate evidence, not re-grading this report. #33 remains open.
