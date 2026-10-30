#!/usr/bin/env bash
# Runs every independent check over the shipped report reader and prints a summary.
# Usage: bash assurance/run.sh          (HYPOTHESIS_PROFILE=dev|ci, default dev; CROSSHAIR_TIMEOUT seconds, default 60)
# Needs: pip install -r assurance/requirements.txt. The package under src/ needs nothing.
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH=src
PROFILE="${HYPOTHESIS_PROFILE:-dev}"
TIMEOUT="${CROSSHAIR_TIMEOUT:-60}"
declare -a SUMMARY

step() {
  local name="$1"; shift
  echo
  echo "== $name"
  if "$@"; then SUMMARY+=("ok      $name"); else SUMMARY+=("FAILED  $name (exit $?)"); fi
}

step "unit tests, unchanged (194 expected)" python3 -m unittest discover -s tests -t . -q
step "PF-3 exhaustive to length 8 (finite proof of that finite statement)" python3 assurance/preflight/exhaustive.py
step "mutants (headline lines must all be killed)" python3 assurance/preflight/mutants.py
step "Hypothesis PF-1 to PF-4, profile $PROFILE (expected failures are the pinned defects)" \
  env HYPOTHESIS_PROFILE="$PROFILE" python3 -m unittest assurance.preflight.test_properties -v
step "parity probe (report only; skips readers that are not present)" python3 assurance/preflight/parity.py
if command -v crosshair >/dev/null 2>&1; then
  step "CrossHair, per-condition timeout ${TIMEOUT}s (no counterexample within bound is not a proof)" \
    crosshair check assurance/preflight/contracts.py --analysis_kind=asserts --per_condition_timeout="$TIMEOUT" --report_all
else
  SUMMARY+=("skipped CrossHair (not installed)")
fi

echo
echo "== summary"
printf '%s\n' "${SUMMARY[@]}"
case "${SUMMARY[*]}" in *FAILED*) exit 1;; esac
