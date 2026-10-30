"""PF-3, exhaustively: every list of outcomes up to length 8, against outcomes.overall and contract._invariants.

Standard library only. This is a complete check of a finite statement: 4^0 + 4^1 + ... + 4^8 = 87,381 lists, each
tested against the three possible `overall` claims. It proves nothing about longer lists or about documents whose
checks are not well-formed records; those are the Hypothesis suite's job.

Run: PYTHONPATH=src python3 assurance/preflight/exhaustive.py
"""

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from egrit_preflight import contract, outcomes  # noqa: E402

MAX_LENGTH = 8
RANK = {"PASS": 0, "UNKNOWN": 1, "FAIL": 2}


def reference_overall(words):
    """The specification: the maximum of FAIL > UNKNOWN > PASS; REQUIRES_HARDWARE contributes nothing."""
    ranked = [RANK[w] for w in words if w in RANK]
    return "PASS" if not ranked else {v: k for k, v in RANK.items()}[max(ranked)]


def checks_for(words):
    return [{"id": f"c{i}", "section": "doctor", "outcome": w, "evidence": "none", "summary": ""}
            for i, w in enumerate(words)]


def main():
    failures = []
    count = 0
    for length in range(MAX_LENGTH + 1):
        for words in itertools.product(outcomes.OUTCOMES, repeat=length):
            count += 1
            checks = checks_for(words)
            expected = reference_overall(words)
            got = outcomes.overall(checks)
            if got != expected:
                failures.append(("overall", words, expected, got))
            # Monotone under append: adding any one outcome never lowers the result.
            for extra in outcomes.OUTCOMES:
                if RANK.get(outcomes.overall(checks + checks_for((extra,))), 0) < RANK[got]:
                    failures.append(("monotone", words, extra, got))
            # REQUIRES_HARDWARE is inert.
            if outcomes.overall(checks + checks_for(("REQUIRES_HARDWARE",))) != got:
                failures.append(("inert", words, got))
            hardware = sorted(c["id"] for c in checks if c["outcome"] == "REQUIRES_HARDWARE")
            for claimed in contract.OVERALL:
                doc = {"overall": claimed, "requires_hardware": hardware}
                problems = [p for p in contract._invariants(doc, checks) if p.startswith("overall is")]
                if bool(problems) != (claimed != expected):
                    failures.append(("_invariants", words, claimed, problems))
    print(f"exhaustive PF-3: {count} outcome lists of length 0 to {MAX_LENGTH} checked, "
          f"{count * len(contract.OVERALL)} (list, claimed overall) pairs against _invariants")
    if failures:
        print(f"FAILURES: {len(failures)}")
        for f in failures[:20]:
            print("  ", f)
        return 1
    print("PF-3 holds for every list up to length 8 (a finite proof of that finite statement)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
