# Docker troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `docker.cli` FAIL | Docker not installed or not on PATH | Install Docker (see README). |
| `docker.daemon` FAIL, "Cannot connect" | Daemon not running | Linux: `sudo systemctl start docker`; macOS: open Docker Desktop. |
| `docker.daemon` FAIL, "permission denied" | User not in the `docker` group | Add the user to `docker`, log in again, or use rootless Docker. |
| `arm64.execution` FAIL on x86_64 Linux | No QEMU binfmt handler | See [linux.md](linux.md). The tool never installs it. |
| smoke FAIL, "exec format error" | arm64 not runnable here | `egrit-preflight doctor`. |
| smoke UNKNOWN, image not available | Image not pulled | `docker pull --platform linux/arm64 <ref>` or pass `--pull`. |
| smoke FAIL, "Timed out" | Emulation is slow | Raise `--timeout`. |
| pull "429 Too Many Requests" | Registry rate limit | Log in with `docker login` or retry later. |
| `docker.buildx` UNKNOWN | Buildx plugin missing | Only needed for registry manifest inspection. https://docs.docker.com/build/install-buildx/ |
