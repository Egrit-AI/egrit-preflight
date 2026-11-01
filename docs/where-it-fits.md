# Where Egrit-Preflight fits

Preflight is the step between "I have an ARM64 image" and "I have a Jetson to test it on". It tells you what can be
settled on an ordinary computer, and gives you an exact list of what cannot.

```
1. Build           docker buildx build --platform linux/arm64 ...   (your image, pinned by digest)
2. Preflight       egrit-preflight doctor / image / smoke / report   (this tool: laptop or CI, no hardware)
3. On a Jetson     the checks Preflight marked REQUIRES_HARDWARE     (CUDA, TensorRT, GPU, power, performance)
4. Deploy          your own process
```

Preflight does not build images, test your model's accuracy, or run anything on a Jetson. It does not replace step 3.
Its job is to make step 3 short: catch the mistakes that do not need a GPU (the wrong architecture, a mutable tag, a
JetPack or CUDA major version that cannot match) before you spend device time on them.

## What each outcome tells you to do next

| Outcome | Meaning | Next step |
|---|---|---|
| `PASS` | Checked, and met. `evidence` says whether this tool observed it or someone declared it. | Carry on. A declared pass is only as good as the declaration. |
| `FAIL` | Checked, and not met (or a refusal, such as an unpinned tag). | Fix it before you use any hardware. |
| `UNKNOWN` | Could not be established: no target record, no digest, no attestation, registry unreachable. | Supply the input its `remediation` names and run again: a target record (`--target`) for `target.*` and `runtime.*`; a local `docker pull` for versions a registry manifest does not show. It is never a pass. |
| `REQUIRES_HARDWARE` | Cannot be decided without a physical Jetson. | Test it on the device. |

Typical fixes: a `FAIL` on `image.architecture` means the image has no `linux/arm64` variant; on `target.l4t` or
`runtime.cuda` it means the image declares a Jetson Linux or CUDA major version your target does not offer; on
`reference.pinned` it means you used a tag, so resolve a digest (`docker buildx imagetools inspect IMAGE`).

## What goes to the device

Every `REQUIRES_HARDWARE` check in a report is the checklist for step 3. The report lists them in `requires_hardware`
and states the standing limits in `limitations`. On the Jetson you still need to confirm, for example:

- the real JetPack and Jetson Linux versions (`cat /etc/nv_tegra_release`) against the target record you passed with
  `--target`, which holds declared values until you replace them with what the device reports;
- that your image's CUDA and TensorRT user space works with the device's driver and libraries, with the NVIDIA runtime
  and device nodes present, which an ARM64 emulation run does not have;
- inference correctness, latency, memory, power and thermal behaviour under your real workload.

A passing smoke test is not a statement about any of these.

## In CI

Run it on every build of an ARM64 image. This repository's own `.github/workflows/ci.yml` does exactly this on a QEMU
runner and on a native ARM64 runner. In outline, as a GitHub Actions step (pin actions by commit, as this repository
does):

```yaml
- name: Preflight
  run: |
    REF="myimage@$(docker buildx imagetools inspect myimage:tag --format '{{.Manifest.Digest}}')"
    egrit-preflight report --image "$REF" --smoke --pull --yes --json -o report.json
- uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9  # v7.0.2
  with:
    name: preflight-report
    path: report.json   # kept with this CI run only; nothing is sent to Egrit or anyone else
```

On an x86_64 runner, register QEMU yourself first (Preflight never does); native ARM64 runners need nothing. Exit codes:
`0` no `FAIL`, `1` at least one `FAIL`, `3` with `--strict` when nothing failed but something is `UNKNOWN`, `4` an
internal error (not a failed check). Use `--strict` if you want unknown data to stop the build, and `--require-digest`
if a mutable tag should be a failure and not a warning.

`--smoke` runs the image's code, so use it only on images you trust. See [security.md](security.md).

## Handing a report to whoever has the hardware

The JSON report is meant to be passed on: it carries the tool version, the host and Docker versions, the exact image
digest, every check with its outcome and evidence grade, and the list of what still needs a device. It states
`hardware_verified: false`, because nothing in it is a device result. The exact meaning of every field, and the rules
every report obeys, are in [report-contract.md](report-contract.md).

## Before you share a report

Read it first. The tool keeps secrets and your Docker configuration out, but the free text in `detail` and `command`
can still contain a path, a user name or an error message from your own machine, and `image.reference` is whatever you
typed. Share the file you have read, not the one a script produced. Sending it anywhere is a step you take; this tool
never does.

## Optional: Egrit alongside Preflight

Egrit, from the same company, is building a separate and optional developer client that an AI assistant can use on
your machine around this tool. It is not part of Preflight, and nothing here needs it.

**Not available yet** as a public release: the client and its guide become public together, and until then the
guide's link below does not open. **No command for it exists** in this tool, and this repository does not document
Egrit's commands.

| | With Preflight alone | With Egrit's client, optional, once public |
|---|---|---|
| Choose a target record | Copy one from [examples/targets](../examples/targets/README.md), or the Orin Nano example | The assistant asks for your device, your exact JetPack release and whether it is installed or planned, then returns the same file from this repository, unchanged, with its source and date. It never guesses a release. |
| Make a report | `egrit-preflight report --json --image IMAGE_REF --target FILE -o report.json`, on your machine | The same command, which you run. Egrit does not run Preflight, start Docker or read a device. |
| See what sharing would send | Read the report yourself | The client lists the fields that would leave your machine and sends nothing. |
| Keep reports with a plan | Keep the files yourself | The client keeps a report you have reviewed in a plan stored on your machine, beside earlier ones, and lists a next check for every `FAIL`, `UNKNOWN` and `REQUIRES_HARDWARE`. |

Egrit's [Preflight journey guide](https://github.com/Egrit-AI/egrit-search/blob/main/docs/preflight-journey.md) gives
its commands, one worked Orin Nano example and which of its steps are available and which are planned.

Whatever Egrit adds, Preflight stays what it is: the free, local CLI needs no account, shows no prompt to upgrade,
sends nothing, and keeps working when run on its own. A hosted step, if one exists, is a separate and explicit
choice you make outside this tool, never a requirement of it. And a report carried into any plan keeps its meaning: an
imported `PASS` is still not a device result, `REQUIRES_HARDWARE` is still not a pass, and a listed attestation is still
not a verified signature.
