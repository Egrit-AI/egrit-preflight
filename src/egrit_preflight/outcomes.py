"""Outcome words and the check record shared by every command."""

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"
REQUIRES_HARDWARE = "REQUIRES_HARDWARE"
OUTCOMES = (PASS, FAIL, UNKNOWN, REQUIRES_HARDWARE)

# Evidence grades, after Egrit's convention: observed by this tool, declared by somebody, or none.
OBSERVED = "observed"
DECLARED = "declared"
NONE = "none"


def check(check_id, outcome, summary, *, evidence=NONE, detail=None, remediation=None, command=None):
    """One check result. Only the fields that carry information are kept, so reports stay small."""
    assert outcome in OUTCOMES, outcome
    rec = {"id": check_id, "outcome": outcome, "summary": summary, "evidence": evidence}
    if detail is not None:
        rec["detail"] = detail
    if remediation:
        rec["remediation"] = remediation
    if command is not None:
        rec["command"] = command
    return rec


def overall(checks):
    """FAIL beats UNKNOWN beats PASS. REQUIRES_HARDWARE is listed apart and never upgrades or hides a result."""
    outcomes = {c["outcome"] for c in checks}
    if FAIL in outcomes:
        return FAIL
    if UNKNOWN in outcomes:
        return UNKNOWN
    return PASS
