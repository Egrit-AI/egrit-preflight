# PyPI release and recovery runbook

This repository releases `egrit-preflight` independently of the combined `egrit` package. The combined package depends on `egrit-preflight>=0.1.0,<0.2`. Publishing here **does not** publish `egrit` or open hosted Search.

Release tracking: [#4](https://github.com/Egrit-AI/egrit-preflight/issues/4).
See [CONTRIBUTING.md](../CONTRIBUTING.md) for the version, release-notes and protected-tag procedure.

## What the first attempt established (13 November 2026)

The `v0.1.0` GitHub release exists with a wheel and sdist. [Actions run 43407556907](https://github.com/Egrit-AI/egrit-preflight/actions/runs/43407556907) built, tested and installed the wheel successfully; the GitHub release job passed. **Only the PyPI job failed.** Its log reported:

```text
invalid-publisher: valid token, but no corresponding publisher
(Publisher with matching claims was not found)
```

The log's GitHub OIDC claims were `repository=Egrit-AI/egrit-preflight`, `workflow_ref=Egrit-AI/egrit-preflight/.github/workflows/release.yml@refs/tags/v0.1.0`, and `environment=pypi`. This was a trusted-publisher registration failure, not evidence of a package build failure.

**Do not infer today's PyPI state from that dated failure.** Before re-running, check the PyPI project and current workflow status. The existing `v0.1.0` tag is protected; never move, delete or recreate it to recover an upload.

## One-time operator setup

The project owner signs in at [pypi.org](https://pypi.org/) with MFA and checks **Account settings → Publishing → Add a new pending publisher** (GitHub):

| Field | Exact value |
| --- | --- |
| PyPI project name | `egrit-preflight` |
| Owner | `Egrit-AI` |
| Repository | `egrit-preflight` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

A pending publisher is **not** a reservation of the project name. Check whether the project already exists and who controls it before proceeding.

In [GitHub repository settings](https://github.com/Egrit-AI/egrit-preflight/settings/environments), confirm the `pypi` environment exists and requires Denis's review before deployment. Restrict deployment to the release-tag pattern `v*` where supported. Verify the rule and review requirement in the actual GitHub settings; a workflow's `environment: pypi` line alone does not prove the setting is protected.

No PyPI API token or long-lived secret is required. Do not grant a runner broader permissions to bypass the review.

## Safe recovery of the existing release

1. Confirm the M4 release gates (green CI, real ARM64 execution in CI, clean wheel installation), release notes and approval to publish. Confirm the immutable `v0.1.0` tag and the existing GitHub release match the original successful build; do not tag the newer `main` as 0.1.0.
2. Check [the PyPI project](https://pypi.org/project/egrit-preflight/) and its [JSON metadata](https://pypi.org/pypi/egrit-preflight/json). If `0.1.0` is already published, **do not retry the upload**; proceed to verification.
3. Confirm the trusted publisher and the `pypi` environment/reviewer with the account owner. A matching publisher alone is not permission to publish.
4. From [the original release run](https://github.com/Egrit-AI/egrit-preflight/actions/runs/43407556907), choose **Re-run jobs → Re-run failed jobs**, *after* the owner authorises this release and the environment review is applied. This should reuse the successful build's uploaded `release` artifact, not rebuild or retag the release. Verify that artifact is still present and unexpired first.
5. Approve only the `pypi` deployment for this release. Check the new job logs; the publish job must upload the **wheel and sdist** by trusted publishing. If a later run cannot reuse the original artifact, stop and plan a reviewed replacement version instead of rewriting `v0.1.0`.
6. If the OIDC exchange still fails, compare the actual PyPI publisher fields with the claims printed in the failed job's log. Fix the account registration; do not add a PyPI token or bypass the required reviewer.

## Verify and close #4

From a clean machine, not inside this checkout:

```sh
python3 -m pip install --upgrade pipx
pipx install egrit-preflight
egrit-preflight --version
egrit-preflight doctor
```

The version command must report `0.1.0`. `doctor` may report missing Docker/QEMU or `REQUIRES_HARDWARE` according to the machine; that is not a PyPI installation failure. Verify PyPI lists **both** `egrit_preflight-0.1.0-py3-none-any.whl` and the `0.1.0` source distribution. Record the PyPI URL, publish run, hashes or provenance where available, install output, and any expected host limitations.

Then change the README's install section from the GitHub-wheel-only instructions to the verified `pipx install egrit-preflight` (or `pip install egrit-preflight`) path, link that change in #4, and close #4 only after every acceptance item is evidenced. Report completion to [the combined-package issue](https://github.com/denissutherland52/Egrit/issues/272).

**Release gates:** Do not mistake a GitHub release for PyPI availability, a synthetic Docker test for Jetson hardware evidence, or an API/CLI dependency for the separate hosted Search launch.
