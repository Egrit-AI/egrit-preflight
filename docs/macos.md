# macOS setup

Install Docker Desktop: https://docs.docker.com/desktop/setup/install/mac-install/ and start it.

- **Apple Silicon:** `linux/arm64` containers run natively in Docker's Linux VM. No x86 emulation is involved. This is
  still not a Jetson: no NVIDIA GPU, driver or device nodes.
- **Intel Mac:** Docker Desktop emulates `linux/arm64` with QEMU when emulation is available. `doctor` reports
  `UNKNOWN` until a smoke test proves it. Emulation is slow.
