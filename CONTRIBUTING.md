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
- Open an issue before large changes. Be kind: see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

By contributing you agree your contribution is licensed under Apache-2.0.
