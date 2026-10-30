# What Egrit-Preflight cannot verify

- **Jetson GPU, CUDA and TensorRT.** QEMU and Docker's ARM64 VM run user-space CPU instructions. They do not emulate the
  Jetson GPU, the NVIDIA driver or `/dev/nv*` device nodes. NVIDIA's Jetson containers rely on libraries and devices
  provided by the host, so even an `import` can fail off-device. An ARM64 `PASS` is not a Jetson `PASS`.
- **Performance.** Emulated timings say nothing about Jetson latency, memory or power.
- **JetPack / L4T compatibility rules.** Target records and image tags are declarations. The tool compares major
  versions and flags disagreement; it does not claim to know NVIDIA's full compatibility matrix.
- **Supply-chain assurance.** `image` reports which SBOM and provenance attestations a registry lists for the arm64 image.
  It does not read their contents, check a signature, or know who the publisher is. A digest fixes the content of an
  image; it does not say who built it or that it is safe.
- **Image safety.** The smoke test runs code from the image. A container is not a security boundary against a hostile
  image or a runtime bug; the isolation flags limit what a careless or merely curious image can do. See
  [security.md](security.md).
- **Mocked tests.** The unit tests use scripted Docker output. They exercise this tool's logic, not real hardware.
- **Flight or production qualification.** Out of scope.

Anything the tool cannot decide is reported `UNKNOWN` or `REQUIRES_HARDWARE`, never `PASS`.
