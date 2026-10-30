# Security policy

Report vulnerabilities privately using GitHub's "Report a vulnerability" (private security advisory) on this
repository. Please do not open a public issue for an undisclosed vulnerability. Expect an acknowledgement within a
few working days.

In scope: command construction in `smoke` (anything that weakens the isolation flags in [docs/security.md](docs/security.md)),
argument injection through image references or target files, secrets leaking into reports. Out of scope: vulnerabilities
in Docker, QEMU or in the images you choose to test.

Supported versions: the latest release and `main`.
