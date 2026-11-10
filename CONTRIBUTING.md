# Contributing

Thanks for helping. Keep the tool small, honest and free of required services.

- Python 3.9+, standard library only. A new runtime dependency needs a strong reason in the issue first.
- Run `PYTHONPATH=src python3 -m unittest discover -s tests -t . -v` before opening a pull request, and add a test with
  every behaviour change. Negative cases (missing Docker, wrong architecture, timeout) use the scripted runner in
  `tests/fakes.py`.
- A change to the report (`report.py`, `contract.py`, `schema/`) is a change to a contract other programs read. Follow
  [docs/report-contract.md](docs/report-contract.md): regenerate the fixtures with `python3 -m tests.make_fixtures`, say
  in the pull request whether the change is additive or breaking, and add a line to `CHANGELOG.md`.
- Never turn a missing or unverifiable fact into `PASS`. Use `UNKNOWN` or `REQUIRES_HARDWARE`.
- Never add automatic privileged operations, hidden network calls, telemetry or account requirements.
- Cite a source (link and retrieval date) for any NVIDIA compatibility claim you add to the documentation.
- New to the repository? [docs/first-pull-request.md](docs/first-pull-request.md) is the short route from fork to merge.
- Open an issue before large changes. Be kind: see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

By contributing you agree your contribution is licensed under Apache-2.0.

## Releasing

A release is a tag; the `Release` workflow does the rest and refuses anything half done.

1. In `CHANGELOG.md`, move the `Unreleased` entries under a `## X.Y.Z (YYYY-MM-DD)` heading.
2. Write `docs/releases/vX.Y.Z.md`: what changed, and what the release cannot verify. The workflow fails without it.
3. Set `__version__` in `src/egrit_preflight/__init__.py` to `X.Y.Z` if it is not already. The workflow fails if the
   tag and the version differ.
4. Merge that pull request, then from an up-to-date `main`:

```bash
git tag -a vX.Y.Z -m "Egrit-Preflight vX.Y.Z"
git push origin vX.Y.Z
```

The workflow refuses a tag that is not on `main`, runs the unit tests, builds the wheel and sdist with the build backend
pinned in `.github/release-constraints.txt`, installs the wheel in a clean venv, and then, in a separate job that runs
no build code, publishes the GitHub release with the notes and both files attached. Create the `v*` tag ruleset before
the first tag, so a tag cannot be moved or deleted afterwards. Publishing to PyPI is a separate step that needs the
trusted publisher to exist first.
