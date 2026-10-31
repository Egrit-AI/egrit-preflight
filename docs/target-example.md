# Example: comparing an image with a target record

Last updated: 2026-10-31.

This page records one real run of `egrit-preflight image` with `--target` set, so you can see what a target record
adds to the output. It complements [l4t-example.md](l4t-example.md), whose run had no target record. Read it with
[limitations.md](limitations.md) beside it.

## What was run

On 2026-10-31 at 11:11 UTC, in a cloud development container (x86_64 Linux, Docker CLI 29.9.2 with no daemon running,
Buildx 0.38.1, egrit-preflight 0.1.0 from this repository's source):

```sh
egrit-preflight image --image dustynv/l4t-pytorch:r36.4.0@sha256:a05c85def9139c21014546451d3baab44052d7cabe854d937f163390bfd5201b --target examples/target-orin-nano-jetpack-6.2.json
egrit-preflight report --json --image dustynv/l4t-pytorch:r36.4.0@sha256:a05c85def9139c21014546451d3baab44052d7cabe854d937f163390bfd5201b --target examples/target-orin-nano-jetpack-6.2.json -o example-target-report.json
```

The image is a community build of PyTorch for Jetson, published on Docker Hub. It is not an NVIDIA image. It was
chosen because its tag states an L4T release and its registry could be reached from the container; `nvcr.io` could not.
The digest is the one `dustynv/l4t-pytorch:r36.4.0` resolved to on 2026-10-31. Nothing was pulled and nothing from the
image was run.

The target record is [examples/target-orin-nano-jetpack-6.2.json](../examples/target-orin-nano-jetpack-6.2.json):
JetPack 6.2, Jetson Linux 36.4.3, CUDA 12.6, TensorRT 10.3, all declared from NVIDIA's release page.

## Keep the tag when you pin

The reference above carries both the tag and the digest (`name:tag@sha256:<digest>`). The digest fixes the content and
gives `reference.pinned` PASS. The tag is where the tool reads the L4T release (`r36.4.0`) when the image's environment
does not set `L4T_VERSION`, and this one does not. Pinned by digest alone (`name@sha256:<digest>`), the same image gives
`target.l4t` UNKNOWN: "Image does not declare an L4T release." Left as a tag alone, `reference.pinned` is UNKNOWN
instead. Writing both gives both checks.

## What came back

```text
Image: dustynv/l4t-pytorch:r36.4.0@sha256:a05c85def9139c21014546451d3baab44052d7cabe854d937f163390bfd5201b  digest: sha256:a05c85def9139c21014546451d3baab44052d7cabe854d937f163390bfd5201b
  [PASS] reference.valid: Image reference is well formed.
  [PASS] reference.pinned: Reference is pinned by digest.
  [PASS] image.manifest: Single-platform manifest and its image config inspected (nothing pulled).
  [PASS] image.architecture: Image provides linux/arm64.
  [UNKNOWN] image.sbom: SBOM attestation not established: no registry manifest list was available for this reference.
  [UNKNOWN] image.provenance: Build provenance attestation not established: no registry manifest list was available for this reference.
  [PASS] target.architecture: Target declares aarch64, which this report covers (linux/arm64). Declared, not observed on a device.
  [PASS] target.jetpack: Target JetPack 6.2 (as declared in the record).
  [PASS] target.l4t: Declared L4T release agrees at major.minor (image r36.4.0, target 36.4.3). Declared, not observed on a device.
  [UNKNOWN] runtime.cuda: Image declares no CUDA version.
  [UNKNOWN] runtime.tensorrt: Image declares no TensorRT version.
  [REQUIRES_HARDWARE] jetson.gpu: Whether this image's CUDA/TensorRT user space works on a Jetson GPU needs a physical device.
      An inspected manifest or an ARM64 smoke test is not Jetson, CUDA or TensorRT compatibility.
Overall: UNKNOWN
```

The full report is [example-target-report.json](example-target-report.json). Its `overall` is FAIL only because the
container had no Docker daemon (`docker.daemon` FAIL, so `arm64.execution` UNKNOWN); the image checks are as above.

| Check | Outcome | Evidence | What it rests on |
|---|---|---|---|
| `target.architecture` | PASS | declared | The record says `aarch64`, which is what the report covers. It checks the record, not the image. |
| `target.jetpack` | PASS | declared | The record states a JetPack release. The image declares none, so nothing is compared. |
| `target.l4t` | PASS | declared | The image tag says r36.4.0 and the record says 36.4.3. They agree at major.minor (36.4), which is the comparison the tool makes. |
| `runtime.cuda`, `runtime.tensorrt` | UNKNOWN | none | The image's environment sets CUDA paths (`CUDA_HOME`, `CUDAARCHS=87`) but no CUDA or TensorRT version, so the record's 12.6 and 10.3 have nothing to be compared with. |
| `image.sbom`, `image.provenance` | UNKNOWN | none | The image has a single-platform manifest and no manifest list, so there are no attestations to list. |
| `jetson.gpu` | REQUIRES_HARDWARE | none | Always, off-device. |

## What this does and does not say

- **Every target PASS is a comparison of declarations.** The record's versions come from NVIDIA's release notes and
  the image's L4T release comes from its tag. Neither was read from a device or from inside the image.
- **Agreement at major.minor is not an exact match.** r36.4.0 and 36.4.3 are different point releases of Jetson Linux.
  The tool reports agreement at the level it compares and says so in the summary.
- **No CUDA or TensorRT comparison happened.** To get one, the image must declare its versions (for example
  `CUDA_VERSION` and `NV_TENSORRT_VERSION` in its environment). This run did not find a public Jetson image that does,
  so it shows neither a CUDA PASS nor a mismatch.
- **It is not a Jetson result.** `hardware_verified` is `false` in the report and stays so off-device.

## Repeating it

Any machine with Docker Buildx and a route to Docker Hub can run the two commands above; no daemon is needed for
`image`. A record of your own device, copied from the example and edited to what `cat /etc/nv_tegra_release` reports,
makes the comparison about your device rather than about a release page.
