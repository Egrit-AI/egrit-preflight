# Security and consent

`smoke` starts a container from an image you name, so it executes that image's code. Run it only on images you trust.
Containers are not a security boundary against a hostile image, a kernel bug or a container-runtime bug.

What Egrit-Preflight asks Docker for: `--platform linux/arm64`, `--pull never`, `--runtime runc` with
`-e NVIDIA_VISIBLE_DEVICES=void` (so a daemon whose default runtime is `nvidia` cannot hand the container a GPU because
the image's own environment asks for one), `--network none`, `--read-only`, `--cap-drop ALL`,
`--security-opt no-new-privileges`, user `65534:65534`, 512 MB memory, 1 CPU, 128 processes, a 16 MB noexec `/tmp`, no
host mounts, no devices, no GPU, and the image entrypoint replaced by one allowlisted command (`uname -m`,
`cat /etc/os-release`, or `python3 -I -B -c <fixed code> <module>`). The module name is validated against a dotted-identifier pattern and
passed as an argument, never spliced into the code. `python-import` executes the named module's top-level code, so it
is only as safe as the image.

`--read-only` does not cover the anonymous volumes Docker creates for an image's `VOLUME` instruction, which are
writable and live on the host disk. Before it runs anything, `smoke` reads the image's declared volumes and mounts a
16 MB noexec tmpfs over each one (at most 16, simple absolute paths only). If it cannot read the list, or a path is
not understood, it runs nothing and reports `UNKNOWN`.

Time and cleanup. The wall-clock timeout, and the removal of the container, are enforced by this process. The container
is force-removed (twice, if the first attempt fails) on timeout, on Ctrl-C and on an internal error. If the CLI is killed
outright (SIGKILL, power loss) a container can outlive it; every container is labelled, so clean up with
`docker ps -aq --filter label=egrit-preflight=1 | xargs -r docker rm -f`. Output captured from any command is capped at
1 MiB per stream, so a container that floods its output cannot exhaust this process's memory.

- It never passes `--privileged`, and never registers QEMU/binfmt for you. If QEMU is missing, `doctor` prints the
  manual recipe (which uses a privileged container); read it before you run it.
- It runs nothing without `--yes`, and pulls nothing without `--pull`.
- Unpinned tags are refused for `smoke` and reported `UNKNOWN` (or `FAIL` with `--require-digest`) for `image`. A digest
  fixes the content; it does not prove who published it. `image` lists attestations the registry publishes (SBOM,
  provenance) as `declared` evidence only and reports `signature_verified: false`; verify signatures and read the
  attestations separately if you need assurance. That includes a digest-named `.sbom` tag (the sigstore convention):
  it counts as listed only once the image itself was found, its contents are not read, and anyone who can push to the
  repository can create one.
- What a report contains. From the host and Docker: the parsed fields (OS, architecture, Docker/Buildx/daemon versions,
  daemon architecture) and the exact command lines. It never contains the raw output of `docker info`, which lists the
  hostname and proxy settings, and `docker info` and `docker image inspect` output is not recorded at all. From the image:
  an allowlist of environment variables (CUDA/TensorRT/L4T/JetPack versions and the NVIDIA runtime variables), only when
  the value is a short token of letters, digits and `._+:,~-`; and labels only when the key mentions l4t, jetpack, cuda
  or tensorrt, or is one of `org.opencontainers.image.{version,revision,created,base.name,base.digest}`, and only when
  the key itself is a short token of letters, digits and `._/-`; at most 32 labels, each value clipped to 100
  characters. The architecture and platform names an image or a registry reports are kept only when they are short
  lowercase tokens; anything else reads as not established. Free-text labels (description, source, url) are never copied, because they can hold internal URLs or
  tokens. From the smoke test: the test command's stdout and stderr, each cut to its last 2000 characters. From `--target`:
  the version fields and a short `name` and `status`, plus the SHA-256 of the file. Review a report before you share it
  anyway: paths and error messages from your own machine can still appear in a check's `detail`.
- Text that came from a container or a registry is scrubbed of control characters before it is printed, so an image
  cannot set your terminal title or redraw the screen. JSON reports are ASCII: every control character, C1 code and
  bidi override is escaped, so `cat report.json` cannot drive the terminal either.
- A malformed or hostile registry or image response (wrong types, deep nesting, huge numbers) gives `UNKNOWN`, not a
  crash. An unexpected internal error exits with code 4 and no result, never with 1 (which means a check failed).
  `--target` files must be regular files of at most 1 MiB. `report -o FILE` refuses a symbolic link or a missing
  directory before it runs anything, creates the file with mode 0600, and does not follow a link at write time.
- `image` contacts the registry (through `docker buildx imagetools`, using your stored Docker credentials) to read
  manifests, the image config a single-platform manifest points to (a small JSON document, not a layer), and, when no
  attestation manifest is listed and the image was found, the manifests of up to four digest-named tags (`.sbom`,
  `.att`, `.sig`, `.vex`). It never pulls layers or runs anything. `smoke` pulls only with `--pull`.
- The result of a smoke test comes from the image's own binaries. A hostile image can print `aarch64` or `imported numpy`
  and claim a pass; `PASS` means "the image said so", which is why only trusted images should be tested.
- No telemetry and no account. The tool opens no network connections itself; Docker does, when it reads a registry or pulls.
