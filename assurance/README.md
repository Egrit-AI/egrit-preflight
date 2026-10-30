# Assurance checks for the report reader

Last updated: 2026-10-30 (dev profile health check, #51) · 2026-10-28

Independent checks over the functions shipped in `src/egrit_preflight/contract.py` and `outcomes.py`: property-based
tests with adversarial generators (Hypothesis), bounded symbolic execution (CrossHair over Z3), an exhaustive
enumeration where the domain is finite, a mutation runner, and a parity probe against the two other readers of a
Preflight report. They check the code as shipped, not a model of it. They are not a proof of the tool, and nothing
here is hardware verification: `hardware_verified` stays `false` throughout.

This folder is never imported by `src/` or `tests/`. The package stays standard-library only; the tools below are
development dependencies of these checks alone. The results and what they mean are written up in
[`docs/assurance/properties.md`](../docs/assurance/properties.md). Tracked internally.

| File | What it is |
|---|---|
| `requirements.txt` | Pinned tools: hypothesis 6.170.13, crosshair-tool 0.0.112, z3-solver 5.3.2.0 |
| `run.sh` | Runs everything in order and prints a summary (`HYPOTHESIS_PROFILE=dev` or `ci`) |
| `preflight/__init__.py` | Hypothesis profiles `dev` (100 examples, no too_slow health check, #51) and `ci` (1000, derandomised, no deadline) |
| `preflight/generators.py` | Strategies: a valid fixture with 0 to 3 random edits, arbitrary JSON trees, raw bytes, documents at the 1 MiB limit |
| `preflight/test_properties.py` | PF-1 to PF-4 as `unittest` classes with `@given`; known defects pinned with `@example` on `expectedFailure` methods |
| `preflight/exhaustive.py` | PF-3 over every outcome list up to length 8, standard library only |
| `preflight/contracts.py` | CrossHair harnesses (assert pre- and post-conditions) around `overall`, `_invariants`, `_pick`, `check_report` |
| `preflight/mutants.py` | Flips one guard or comparison at a time in memory and reports which mutants the fixtures kill |
| `preflight/parity.py` | Feeds the same generated documents to the Egrit-elevator and Egrit client readers, by path, report only |

## Running

```sh
pip install -r assurance/requirements.txt
bash assurance/run.sh                      # dev profile: 100 examples, seed varies per run; about a minute plus CrossHair's timeouts
HYPOTHESIS_PROFILE=ci bash assurance/run.sh   # 1000 examples, derandomised: the reproducible record
```

Each step can be run alone; the commands are at the top of each file. `.hypothesis/` (the example database) is
git-ignored; the pinned examples make the known counterexamples reproduce without it.

## What a result means

- Hypothesis `ok`: no counterexample was found under the profile's settings and seed. Not a proof.
- Hypothesis `expected failure`: a known defect, pinned by its minimal input, still stands. The day it is fixed the
  method reports `unexpected success`, and the `expectedFailure` mark should then be removed. Four stand today, see
  below. The general properties `assume` away exactly those input shapes and say so in the code.
- `exhaustive.py`: a finite proof of PF-3 for lists up to length 8, and nothing beyond that length.
- CrossHair "no counterexample within bound": the symbolic search ran out of its per-condition timeout without
  finding an input that breaks a postcondition. Not a proof.
- `mutants.py`: a killed mutant means some input in the fixture set changes the reader's verdict when that line is
  flipped; a survivor means no input here exercises that line both ways. It says nothing about lines it does not mutate.
- `parity.py`: a disagreement is a difference between readers on a generated document; it is a finding for the
  owner of that reader, not a verdict on which reader is right.

## Known defects pinned today (not fixed here)

1. `checks[0].outcome = []` makes `check_report` raise `TypeError` at `contract.py:137` instead of returning a problem.
2. `requires_hardware = [1, "a"]` makes it raise `TypeError` at `contract.py:142`.
3. `uncertainties[0].outcome = "VERIFIED"` is accepted and exported by `allowlisted_view` (uncertainty items are not
   validated, `contract.py:103` to `104`).
4. `uncertainties[0] = ""` and `image.provenance.attestations = ""` are accepted, and `allowlisted_view` holds `None`
   at those paths, a leaf the document does not have (`_pick` substitutes `None` for a shape mismatch).

Fixing them is a separate decision and a separate pull request each; this folder changes nothing under `src/`.

## Not established

The property statements were drafted with an LLM and must be read by a person against `docs/report-contract.md`.
Independence holds for the checking (Hypothesis, Z3, the enumeration), not for the authoring. Nothing here says
anything about a Jetson, a GPU, CUDA or TensorRT.
