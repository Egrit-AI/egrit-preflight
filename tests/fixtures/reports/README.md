# Report fixtures

Test data for anything that reads an Egrit-Preflight report, including this repository's own tests. The contract they
illustrate is in [docs/report-contract.md](../../../docs/report-contract.md).

- `valid/`: reports a reader must accept. Real output of the CLI against a scripted Docker with a fixed clock; the
  hosts, versions and digests are made up.
- `invalid/`: a valid report with one thing broken, or text that is not a report. A reader must reject each as a whole.
  The file name says what is wrong.

Do not edit these by hand. After any change to the report run `python3 -m tests.make_fixtures` from the repository root
and review the diff; `tests/test_contract.py` fails if they are stale.
