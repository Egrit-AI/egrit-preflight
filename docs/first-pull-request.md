# Your first pull request

Last updated: 2026-11-05

For someone who knows GitHub and has not yet contributed to this repository. You do not need write access: you work on a fork. Read [CONTRIBUTING.md](../CONTRIBUTING.md) first; this page only covers the route.

## Steps

1. **Fork** `Egrit-AI/egrit-preflight` on GitHub, then clone your fork.
2. **Add the original as `upstream`** so you can stay current:
   `git remote add upstream https://github.com/Egrit-AI/egrit-preflight.git`
3. **Branch from an up-to-date `main`**, never work on `main` itself:
   `git fetch upstream && git switch -c docs/short-name upstream/main`
   Use a short prefix such as `docs/`, `fix/` or `feat/`.
4. **Make one change.** One concern per pull request. If you found two problems, make two pull requests.
5. **Run the tests** before pushing:
   `PYTHONPATH=src python3 -m unittest discover -s tests -t . -v`
   A behaviour change needs a test. A wording change in a check's text counts as a behaviour change.
6. **If anything that appears in a report changed,** regenerate the fixtures with `python3 -m tests.make_fixtures`, review the diff, and add a line to `CHANGELOG.md`. That covers check text in `doctor.py`, `image.py` or `smoke.py` as well as `report.py`, `contract.py` and `schema/`. The fixtures are real CLI output, so a one-line wording change can rewrite many of them. If the tests say the fixtures are stale, this is the step you missed.
7. **Commit** with a short message in the style of `git log`: `area: what changed (#issue)`.
8. **Push to your fork** and open a pull request against `Egrit-AI/egrit-preflight:main`.
9. **In the description:** link the issue (`Refs #5`, or `Closes #5` only if it finishes it), say what you changed, what you ran, and what you did not check. Say whether a report change is additive or breaking.

## What happens next

- Required CI checks must pass. `main` is protected: no direct pushes, no force-push.
- A maintainer reviews and merges. Expect comments; push fixes to the same branch and they appear on the pull request.
- Because you are on a fork, CI from a first-time contributor may wait for a maintainer to approve the run.

## House rules that catch people out

- Python standard library only. No new dependency without an issue first.
- Never turn something unverified into `PASS`. Use `UNKNOWN` or `REQUIRES_HARDWARE`.
- Any NVIDIA claim in the docs needs a source link and a retrieval date.
- British English. No secrets, local paths or personal data in anything you attach: review a `report.json` before you commit or paste it.
- Do not add telemetry, hidden network calls or required accounts.

## Choosing a change

Look at the open issues, and say on the issue that you are taking it so nobody duplicates the work. Open an issue first for anything large.
