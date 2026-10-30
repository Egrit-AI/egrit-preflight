# PF-1 to PF-4: properties of the report reader, and what was found

Last updated: 2026-10-30 (probe 2 enforced as rule 11, #45; PF-1 asserts it and its generator drops the GPU check) · 2026-10-30 (probe 1 enforced, #44; rule 3 recorded as a known limit, #33) · 2026-10-28 (counterexamples 1 and 2 fixed, #31; 3 and half of 4, #32)

Subject: `src/egrit_preflight/contract.py` and `src/egrit_preflight/outcomes.py` at commit
`aa7ee980ac4ccc25ee0fbfee6e45112c0ec65b02` (main, 2026-10-28). Code and commands: [`assurance/`](../../assurance/README.md).
Tracked internally. The canonical pilot report is
`docs/research/formal-verification/formal-assurance-pilot-2026-10.md` in the Egrit repository.

## Correspondence

These properties are checked against the functions as shipped in src/egrit_preflight/contract.py and outcomes.py at
commit aa7ee980ac4ccc25ee0fbfee6e45112c0ec65b02, not against a model of them. Hypothesis is a bounded random search
with shrinking: a pass means no counterexample was found under the stated settings and seed, not a proof. CrossHair is
a bounded symbolic search over Z3: a pass means no counterexample was found within the per-condition timeout. The
exhaustive run for PF-3 is complete for lists up to length 8 and is a proof only of that finite statement.

Tools: hypothesis 6.170.13, crosshair-tool 0.0.112, z3-solver 5.3.2.0, CPython 3.13 in the session that produced
these results (the numbers below are from CPython 3.13; the optional CI job runs them on 3.12 and its log is the record there).

## The properties

| ID | Statement (one sentence) | Kind | Tool and bound | Result on this commit |
|---|---|---|---|---|
| PF-1 | If `load_report(b)` returns `(doc, [])` then `doc.hardware_verified is False`, `doc.image.provenance.signature_verified is False` wherever `image.provenance` is an object, every check with id `jetson.gpu` has outcome `REQUIRES_HARDWARE` and evidence `none` (#44), `checks` is non-empty with a `jetson.gpu` check that `requires_hardware` names (#45), `doc.overall == outcomes.overall(doc.checks)` and `requires_hardware` lists exactly the `REQUIRES_HARDWARE` ids. | source-level bounded check, test-derived | Hypothesis, 100 examples (`dev`) and 1000 (`ci`, derandomised), generator: valid fixture plus 0 to 3 edits, including `gpu_evidence` and `drop_gpu` (since #44 and #45); plus every committed fixture | no counterexample within bound (both profiles); the 6 valid fixtures accepted, the 21 invalid rejected |
| PF-2 | `load_report` never raises on any bytes or text and returns `(None, problems)` exactly when `problems` is non-empty; `check_report` returns a list on any JSON value. | source-level bounded check, test-derived | Hypothesis over raw bytes, arbitrary JSON trees and edited fixtures; documents of exactly 1 MiB minus 1, 1 MiB and 1 MiB plus 1 | **two counterexamples**, pinned (below), both **fixed** in #31; no others within bound once those two input shapes are excluded |
| PF-3 | `outcomes.overall` is the maximum of `FAIL > UNKNOWN > PASS`, never lowered by appending, unchanged by `REQUIRES_HARDWARE`, and `_invariants` reports an `overall` problem exactly when the claimed `overall` differs from it. | source-level finite proof of that finite statement (enumeration); bounded check (Hypothesis) | `exhaustive.py`: all 87,381 lists of length 0 to 8 (4^0 to 4^8), each against the 3 possible claims, 262,143 pairs; Hypothesis: lists up to 200 | holds for every list up to length 8; no counterexample within bound up to 200 |
| PF-4 | `allowlisted_view(doc)` raises `Rejected` exactly when `check_report(doc)` is non-empty; otherwise it is a sub-tree of `doc` (every leaf is the document's value at that path and no path leaves `ALLOWLIST`) and every `outcome`, `evidence` and `overall` leaf is in its enum. | source-level bounded check, test-derived | Hypothesis, same generator and profiles as PF-1 | **two counterexample classes**, pinned (below); the first and half of the second **fixed** in #32; the weakened sub-tree clause ("or `None` where the document's shape differs from the allowlist") has no counterexample within bound |

Expected failures in `test_properties.py`: 4 (`PF2...outcome_list`, `PF2...mixed_requires_hardware`,
`PF4...uncertainty_outcome_unchecked`, `PF4...strict_subtree`). Suite result on this commit, both profiles:
`OK (expected failures=4)`, 15 tests. After the fix for counterexamples 1 and 2 (egrit-preflight #31): the two PF-2
pins are ordinary regression tests and the general PF-1, PF-2 and PF-4 properties no longer exclude those shapes;
`OK (expected failures=2)`, 15 tests, on the `ci` profile. After the fix for 3 and the uncertainty half of 4
(egrit-preflight #32, rule 10): `OK (expected failures=1)`, 16 tests, on the `ci` profile; the one left is the scalar
`attestations` case of 4.

## Counterexamples found (exact minimal inputs)

Each starts from `tests/fixtures/reports/valid/pass-observed.json`; Hypothesis shrank each to one edit.

| # | Edit | What the reader does | Where | Property |
|---|---|---|---|---|
| 1 | `checks[0].outcome = []` | `check_report` raises `TypeError: unhashable type: 'list'` (set comprehension over outcomes); `load_report` does not catch it | `contract.py:137` | PF-2; **fixed** in #31 (rejected: `outcome must be one of`) |
| 2 | `requires_hardware = [1, "a"]` | raises `TypeError: '<' not supported between instances of 'str' and 'int'` (`sorted` over mixed types) | `contract.py:142` | PF-2; **fixed** in #31 (rejected: `requires_hardware must be an array of strings`) |
| 3 | `uncertainties[0].outcome = "VERIFIED"` | accepted (`check_report` returns `[]`), and `allowlisted_view` exports `{"id": "jetson.gpu", "outcome": "VERIFIED", ...}` | `contract.py:103` to `104` (only `isinstance(list)`); allowlist line 45 | PF-4; **fixed** in #32 (rule 10) |
| 4 | `uncertainties[0] = ""`; also `image.provenance.attestations = ""` | accepted; the view holds `None` at that path, a leaf the document does not have (`_pick` returns `None` on a shape mismatch) | `contract.py:167` to `174` | PF-4, strict sub-tree clause; the `uncertainties` case **fixed** in #32, the `attestations` case open |

Nothing is partly imported in 1 and 2 (the exception propagates), but the reader crashes instead of rejecting, which
`docs/report-contract.md` ("fail closed ... nothing is partly accepted") does not promise and a CI script would see as
an error, not a verdict. 3 is a declared word becoming exported data: the contract says an unknown `outcome` is
rejected, and this is the one place it is not. 4 is weaker than 3 (`None` strengthens nothing) and is recorded for
completeness. None of the four touches the headline clause of PF-1: `hardware_verified` must be the literal `False`
(`"false"`, `0` and a missing key are all rejected, checked by fixtures and by the generator).

## Rules the document states that the reader does not enforce (probes, not fixed)

Each was probed in memory on this commit against `check_report`; each is accepted. Whether each is a defect is a
decision for the owner (`report-contract.md:52`, "Always includes `jetson.gpu`", makes the second the strongest).

| Probe | Document says | Reader does |
|---|---|---|
| `jetson.gpu` check with `evidence: "observed"` | an `observed` check was observed by this tool; a GPU result cannot come from it | rule 2 (`contract.py:146`) checks the outcome only; accepted. **Enforced since #44**: rejected, fixture `gpu-check-observed.json` |
| no `jetson.gpu` check at all; `checks: []` with `overall: "PASS"` and `requires_hardware: []` | `requires_hardware` "always includes `jetson.gpu`" | nothing requires a `jetson.gpu` check to exist; accepted. **Enforced since #45** (rule 11): rejected, fixtures `checks-empty.json`, `gpu-check-missing.json`, `requires-hardware-without-gpu.json`; PF-1 now asserts it, and its generator's `drop_gpu` edit removes the check consistently |
| `provenance.smoke_executed` flipped | `smoke_executed` says whether a container was started | never cross-checked against the `smoke` section; accepted (and `image.provenance.status` is not on the reader's checklist, though the schema rejects a value outside its enum) |

## Known limits (owner's answer on #33, 2026-10-29)

The reader does not cross-check `provenance.smoke_executed` against the `smoke` section, and does not check
`image.provenance.status` (the schema rejects a value outside its enum; `check_report` does not look). A report with
`smoke_executed` flipped is accepted. These stay known limits until a consumer needs them; they are not defects of the
other rules.

## Mutation run (`mutants.py`)

38 single-point mutants of `contract.py` (every `need(...)` in `check_report` negated, 21; every comparison in
`_invariants` flipped, 12) and `outcomes.py` (comparisons in `overall` flipped, 2; returned word replaced, 3), each run
over 27 fixtures, 12 hand-made documents and all 341 outcome lists up to length 4. **38 killed, 0 survived.** The
headline lines and the witness that kills each, preferring an input the mutant wrongly accepts:

| Line | Mutant | Killed by |
|---|---|---|
| `contract.py:94` | `need(not hardware_verified is False)` | `invalid/hardware-verified-missing.json` accepted (+14 more inputs differ) |
| `contract.py:129` | `need(not signature_verified is False)` | `invalid/signature-verified-true.json` accepted (+9) |
| `contract.py:139` | `in` flipped; `!=` flipped | `invalid/overall-pass-over-a-fail.json` accepted (+2; +13) |
| `contract.py:146` | `== "jetson.gpu"` flipped; `!= "REQUIRES_HARDWARE"` flipped | `valid/declared-target.json` rejected (+10 each) |
| `outcomes.py:31` to `34` | `FAIL in` and `UNKNOWN in` flipped; `return UNKNOWN` for `FAIL`; `return PASS` for `UNKNOWN` | the empty list, `[FAIL]`, `[UNKNOWN]` (+340, +120, +219, +89) |

A kill says the line decides something on this input set; it says nothing about lines the runner does not mutate.

## CrossHair (`contracts.py`)

Command: `PYTHONPATH=src crosshair check assurance/preflight/contracts.py --analysis_kind=asserts --per_condition_timeout=60`,
CPython 3.13, crosshair-tool 0.0.112, z3-solver 5.3.2.0.

Exit status 0; with `--report_all` CrossHair prints `Not confirmed` for each of the five harness functions, which
is its word for: the symbolic search ran out of the per-condition timeout without finding a counterexample and
without exhausting every path. No function was confirmed (CrossHair confirms only when it exhausts the paths).

| Harness (line) | Wraps | Outcome |
|---|---|---|
| `overall_is_max` (27) | `outcomes.overall` | no counterexample within bound (60 s) |
| `invariants_accept_overall_iff_equal` (36) | `contract._invariants` | no counterexample within bound (60 s) |
| `pick_is_subtree` (53) | `contract._pick` over a three-key allowlist | no counterexample within bound (60 s) |
| `check_report_is_total` (74) | `contract.check_report` | no counterexample within bound (60 s) |
| `accepted_implies_headline` (83) | `contract.check_report` with PF-1's clauses as postconditions | no counterexample within bound (60 s) |

Calibration: counterexample 1 (`checks[i].outcome` a list) lies inside the input family of `check_report_is_total`
(`Check` values may be `List[str]`), and CrossHair did not reach it in 60 s: the path must first satisfy
`schema_version == "1"`, `tool.name`, and the other guards. Hypothesis, starting from a valid fixture, found it in
seconds. On this reader the fixture-based generator is the stronger search; CrossHair's "no counterexample" for
`check_report` should be read as weak evidence. CrossHair 0.0.112 ran on CPython 3.13 here without error.

## Parity with the other two readers (`parity.py`, report only)

500 documents from the PF-1 generator (derandomised, so the set is the same on every run), each given to the
reference reader, to Egrit-elevator's `bench/elevator_bench/preflight_intake.py` (`parse`) and to Egrit's
`clients/python/src/egrit/preflight.py` (`parse_report`, pinned to Preflight commit `2818a45`). Nothing in those
repositories was changed. Neither reader raised anything other than its own error type on any document.

| Reader | Accepts what the reference rejects | Rejects what the reference accepts | First disagreements |
|---|---|---|---|
| Egrit-elevator `preflight_intake.parse` | 5 | 27 | Accepts: `checks[12].summary` deleted (`unknown-registry-down.json`); `checks[1].summary = 1677102` (`fail-arch-mismatch.json`); `checks[4].summary = None` (`doctor-only.json`, twice). All five are a non-string or missing `summary`: the reference requires text, the Elevator reader never reads `summary` and so does not check it. Rejects: `uncertainties[i].section` or `.summary` replaced by an integer or `{}` (`FIELD_ENUM`, `FIELD_MISSING`); `provenance.smoke_executed = {}` (`FIELD_TYPE`): it validates uncertainty records and `smoke_executed`, the reference does not. |
| Egrit client `preflight.parse_report` | 0 | 50 | All `SOURCE_SCHEMA` or `PROJECTION_SCHEMA`: an edited `commands[]` entry, an `uncertainties[i]` record with a non-enum `section` or non-string `summary`, `smoke_executed = {}`. It validates the whole pinned schema, the reference checks only its listed rules. |

Reading: the Egrit client is strictly stricter on this sample; the Elevator reader is stricter on uncertainty
records and `smoke_executed` and looser only on a field it never imports. Neither accepts a document that breaks
PF-1's clauses. These are findings for the owners of those readers, not verdicts.

## Not established

- Nothing here is a proof of the tool, and nothing is hardware verification: `hardware_verified` stays `false`,
  and no statement about a Jetson, a GPU, CUDA or TensorRT follows from any result above.
- The Hypothesis results are "no counterexample within bound" under the recorded profile; the generator edits a
  valid fixture at most three times and never produces a report from nothing, so a shape reachable only by four or
  more edits is outside its reach.
- The CrossHair harnesses quantify over the simplified types in `contracts.py`, not over every JSON value; what a
  "no counterexample" there covers is exactly those types.
- PF-3's enumeration stops at length 8; `_invariants` and `overall` have no length-dependent branch, but that is a
  reading of the code, not something the enumeration shows.
- The property statements were drafted with an LLM; a person must read them against `docs/report-contract.md`.
  Independence holds for the checking, not the authoring.
- Which of the four counterexamples and three probes are defects is a decision for the owner; none is fixed here.
- Results were produced on CPython 3.13; the optional CI job (Egrit-AI/egrit-preflight#34) runs them on 3.12 and its uploaded log is the record for that version.
- Rules 5, 6, 8 and 9 of `docs/report-contract.md` are covered by the fixtures and the mutant runner only, not by any PF property.
- The mutant runner is a differential check over the input set, not a property check: a vacuous predicate would give the same kill count; what it establishes is that each guard line changes a verdict on some input.
