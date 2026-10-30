# Example: inspecting an NVIDIA L4T image off-device

Last updated: 2026-10-30.

This page records one real run of `egrit-preflight image` against an NVIDIA L4T image, pinned by digest, from a
machine that is not a Jetson. It shows what the tool can establish about such an image from its registry alone, and
what it cannot. Read it with [limitations.md](limitations.md) beside it.

## What was run

On 2026-10-30 at 13:25 UTC, on a GitHub Actions `ubuntu-latest` runner (x86_64 Linux, Docker 29.4.2, Buildx 0.38.1,
egrit-preflight 0.1.0), by the `L4T inspect` workflow
(`.github/workflows/l4t-inspect.yml`, [run 41063039600](https://github.com/Egrit-AI/egrit-preflight/actions/runs/41063039600)):

```sh
egrit-preflight image --image nvcr.io/nvidia/l4t-jetpack@sha256:34ccf0f3b63c6da9eee45f2e79de9bf7fdf3beda9abfd72bbf285ae9d40bb673
egrit-preflight report --json --image nvcr.io/nvidia/l4t-jetpack@sha256:34ccf0f3b63c6da9eee45f2e79de9bf7fdf3beda9abfd72bbf285ae9d40bb673 -o l4t-report.json
```

The digest is the one `nvcr.io/nvidia/l4t-jetpack:r36.4.0` resolved to when it was read anonymously on 2026-10-29.
Pin by digest, not by tag: the tag can move, and this page does not claim that any particular L4T tag exists today.
No NGC login was needed to read this image's manifest. Nothing was pulled and nothing from the image was run.

## What came back

```text
Image: nvcr.io/nvidia/l4t-jetpack@sha256:34ccf0f3…bb673  digest: sha256:34ccf0f3…bb673
  [PASS] reference.valid: Image reference is well formed.
  [PASS] reference.pinned: Reference is pinned by digest.
  [PASS] image.manifest: Single-platform manifest and its image config inspected (nothing pulled).
  [PASS] image.architecture: Image provides linux/arm64.
  [PASS] image.sbom: SBOM is listed by the publisher as a digest-named tag for this image. Its contents and any
         signature were not verified; a digest fixes content, not who published it.
  [UNKNOWN] image.provenance: Build provenance attestation not established: the publisher lists digest-named tags
         for this image, none of them an attestation bundle.
  [UNKNOWN] target.jetpack, target.l4t, runtime.cuda, runtime.tensorrt: not compared. No target record supplied.
      -> Pass a target record: --target examples/target-orin-nano-jetpack-6.2.json, copied and edited.
  [REQUIRES_HARDWARE] jetson.gpu: Whether this image's CUDA/TensorRT user space works on a Jetson GPU needs a
         physical device.
Overall: UNKNOWN
```

The full report is [example-l4t-report.json](example-l4t-report.json). Its `overall` is FAIL only because the
runner's own `arm64.execution` check failed (no QEMU handler on that runner); the image checks are as above.

| Check | Outcome | Evidence | What it rests on |
|---|---|---|---|
| `image.architecture` | PASS | observed | The image config read from the registry says `arm64`. L4T images publish a single-platform manifest, so there is no platform list. |
| `image.sbom` | PASS | declared | NVIDIA publishes the SBOM as a digest-named tag (`…:sha256-<digest>.sbom`). The tool saw that the tag exists. It did not read the SBOM or verify a signature. A `.sig` tag was also seen and is recorded; `signature_verified` stays `false`. |
| `image.provenance` | UNKNOWN | none | No attestation bundle among the published tags. |
| `runtime.cuda`, `runtime.tensorrt`, `target.*` | UNKNOWN | none | The config's environment declares only `NVIDIA_DRIVER_CAPABILITIES` and `NVIDIA_VISIBLE_DEVICES`, no CUDA or TensorRT version, and no target record was given. |
| `jetson.gpu` | REQUIRES_HARDWARE | none | Always, off-device. |

## What this does and does not say

- **It is not a Jetson result.** The runner has no NVIDIA driver, no CUDA or TensorRT libraries and no `/dev/nv*`
  device nodes. L4T containers take those from the host, so even `import tensorrt` can fail off-device while being
  fine on the device, and the other way round. `hardware_verified` is `false` in the report and will stay so.
- **A PASS here is a registry fact.** The image is built for `linux/arm64` and its publisher lists an SBOM for it.
  That is all. Whether it runs, and whether the SBOM is true, is not established.
- **Declared versions were not available from this image's config.** The JetPack, L4T, CUDA and TensorRT comparisons
  need a target record (`--target`) and an image that declares its versions, or a local pull. See
  [examples/target-orin-nano-jetpack-6.2.json](../examples/target-orin-nano-jetpack-6.2.json).
- **If the registry cannot be reached**, `image.manifest` and the checks after it read UNKNOWN with a remediation, not
  FAIL. That is the designed result; the tool does not guess.

## Repeating it

Any machine with Docker and a route to `nvcr.io` can run the two commands above. In this repository, Actions →
"L4T inspect" → Run workflow does the same on an Ubuntu runner and uploads the output; the default input is the digest
above, and another `name@sha256:<digest>` can be given instead.
