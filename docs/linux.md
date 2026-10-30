# Linux setup

1. Install Docker Engine: https://docs.docker.com/engine/install/ . Make sure your user can run `docker info`.
2. **x86_64 only:** register QEMU for arm64 once. Check first: `egrit-preflight doctor`. If it reports no handler,
   run one of these yourself, as an administrator:
   - `docker run --privileged --rm tonistiigi/binfmt --install arm64` (privileged; read https://github.com/tonistiigi/binfmt first)
   - install `qemu-user-static` and `binfmt-support` with your package manager.
3. **ARM64 Linux** (including a Jetson itself): no emulation needed.
4. `egrit-preflight doctor` should now show `arm64.execution` as PASS.

Emulated ARM64 is much slower than native. Raise `--timeout` if a test times out.
