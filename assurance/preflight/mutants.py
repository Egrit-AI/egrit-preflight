"""Mutation runner for the reader, standard library only: does each guard line actually decide something?

It parses src/egrit_preflight/contract.py and outcomes.py, makes one change at a time in memory (never on disk),
executes the mutated source into a fresh module and compares its verdicts (accept or reject, and `overall`) with
the shipped reader's over every committed fixture, a few hand-made documents and every short outcome list. This is a
differential check over that input set, not a property check: a mutant that changes any verdict is "killed"; one
that changes none "survives", which means no input in this set exercises that line both ways. It measures the
sensitivity of the input set to each guard, which is what protects the PF properties from being vacuous.

Mutations: `need(cond, ...)` becomes `need(not cond, ...)` anywhere in check_report; one comparison operator is
flipped in _invariants and in outcomes.overall; one returned outcome word in overall is replaced by the next.

Exit status is non-zero if a mutant of a headline line survives: in contract.py, hardware_verified,
signature_verified, overall agrees with the checks, jetson.gpu is REQUIRES_HARDWARE, jetson.gpu evidence is none
(#44), requires_hardware names jetson.gpu (#45), and rule 10 (an uncertainty's outcome, and the uncertainties match
the checks); in outcomes.py, lines 31 to 34 (FAIL over UNKNOWN over PASS). HEADLINE below holds the line numbers.
Rule 11's three guards (#45) overlap with rule 3: an empty checks list or a missing jetson.gpu check forces a
requires_hardware without jetson.gpu, so each guard alone mostly changes the message, and the fixture phrases in
tests/test_contract.py are what pin them. "if not checks" makes no mutant here (a unary not is not mutated), and
the "checks include jetson.gpu" comparison's mutant survives by design.

Run: python3 assurance/preflight/mutants.py
"""

import ast
import copy
import itertools
import json
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "egrit_preflight"
FIXTURES = REPO / "tests" / "fixtures" / "reports"
HEADLINE = {"contract.py": {98, 138, 146, 156, 167, 180, 182, 194}, "outcomes.py": {31, 32, 33, 34}}
# The text each headline line must still carry; if the file moves, this fails loudly instead of relabelling mutants.
HEADLINE_TEXT = {("contract.py", 98): "hardware_verified", ("contract.py", 156): "signature_verified",
                 ("contract.py", 167): "expected_overall", ("contract.py", 180): "jetson.gpu",
                 ("contract.py", 182): "evidence != \"none\"",
                 ("contract.py", 194): "\"jetson.gpu\" not in listed",
                 ("contract.py", 138): "UNCERTAIN", ("contract.py", 146): "set(pairs) == expected",
                 ("outcomes.py", 31): "FAIL in outcomes", ("outcomes.py", 32): "return FAIL",
                 ("outcomes.py", 33): "UNKNOWN in outcomes", ("outcomes.py", 34): "return UNKNOWN"}


def check_headline_lines():
    for (name, line), text in HEADLINE_TEXT.items():
        actual = (SRC / name).read_text().splitlines()[line - 1]
        if text not in actual:
            raise SystemExit(f"{name}:{line} no longer carries {text!r}: update HEADLINE in mutants.py")
FLIP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot,
        ast.IsNot: ast.Is, ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt}
NEXT_WORD = {"FAIL": "UNKNOWN", "UNKNOWN": "PASS", "PASS": "FAIL"}


def load_module(name, source):
    module = types.ModuleType(name)
    module.__file__ = str(SRC / f"{name}.py")
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def _in_function(tree, names):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            for inner in ast.walk(node):
                yield inner


def mutants_of(filename, source):
    """Yield (description, line, mutated_source) for every single-point mutation of this file."""
    tree = ast.parse(source)
    if filename == "contract.py":
        for node in _in_function(tree, {"check_report"}):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "need" and node.args:
                mutated = copy.deepcopy(tree)
                for m in _in_function(mutated, {"check_report"}):
                    if isinstance(m, ast.Call) and isinstance(m.func, ast.Name) and m.func.id == "need" \
                            and m.lineno == node.lineno and m.col_offset == node.col_offset:
                        m.args[0] = ast.UnaryOp(op=ast.Not(), operand=m.args[0])
                yield f"need(not ...) at line {node.lineno}", node.lineno, ast.unparse(ast.fix_missing_locations(mutated))
        compare_scope = {"_invariants"}
    else:
        compare_scope = {"overall"}
    for node in _in_function(tree, compare_scope):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in FLIP:
            mutated = copy.deepcopy(tree)
            for m in _in_function(mutated, compare_scope):
                if isinstance(m, ast.Compare) and m.lineno == node.lineno and m.col_offset == node.col_offset:
                    m.ops = [FLIP[type(m.ops[0])]()]
            yield f"flip {type(node.ops[0]).__name__} at line {node.lineno}", node.lineno, ast.unparse(mutated)
    if filename == "outcomes.py":
        for node in _in_function(tree, {"overall"}):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Name) and node.value.id in NEXT_WORD:
                mutated = copy.deepcopy(tree)
                for m in _in_function(mutated, {"overall"}):
                    if isinstance(m, ast.Return) and m.lineno == node.lineno:
                        m.value = ast.Name(id=NEXT_WORD[node.value.id], ctx=ast.Load())
                yield f"return {NEXT_WORD[node.value.id]} instead of {node.value.id} at line {node.lineno}", \
                    node.lineno, ast.unparse(mutated)


def handmade():
    """Documents that each break one rule the fixtures may not isolate, plus a few that obey all of them."""
    with open(FIXTURES / "valid" / "pass-observed.json", "rb") as fh:
        base = json.load(fh)
    docs = {}

    def variant(name, mutate):
        doc = copy.deepcopy(base)
        mutate(doc)
        docs[name] = doc

    variant("hardware_verified_true", lambda d: d.__setitem__("hardware_verified", True))
    variant("hardware_verified_missing", lambda d: d.pop("hardware_verified"))
    variant("signature_verified_true", lambda d: d["image"]["provenance"].__setitem__("signature_verified", True))
    variant("provenance_null", lambda d: d["image"].__setitem__("provenance", None))
    variant("gpu_pass", lambda d: d["checks"][4].__setitem__("outcome", "PASS"))
    variant("gpu_fail", lambda d: d["checks"][4].__setitem__("outcome", "FAIL"))
    variant("overall_pass_over_unknown", lambda d: d.__setitem__("overall", "PASS"))
    variant("overall_fail_over_unknown", lambda d: d.__setitem__("overall", "FAIL"))
    variant("image_null", lambda d: d.__setitem__("image", None))
    variant("no_target", lambda d: d.__setitem__("target", {"architecture": "linux/arm64", "record": None}))

    def all_pass(d):
        for c in d["checks"]:
            if c["outcome"] == "UNKNOWN":
                c["outcome"] = "PASS"
        d["overall"] = "PASS"
    variant("overall_pass_consistent", all_pass)

    def one_fail(d):
        d["checks"][0]["outcome"] = "FAIL"
        d["overall"] = "FAIL"
    variant("overall_fail_consistent", one_fail)
    return docs


def verdicts(contract, outcomes):
    """The observable behaviour of a reader: one entry per input."""
    out = {}
    for path in sorted((FIXTURES / "valid").glob("*.json")) + sorted((FIXTURES / "invalid").glob("*.json")):
        out[path.parent.name + "/" + path.name] = _verdict(contract, path.read_bytes())
    for name, doc in handmade().items():
        out["handmade/" + name] = _verdict(contract, json.dumps(doc).encode("utf-8"))
    for length in range(5):
        for words in itertools.product(("PASS", "FAIL", "UNKNOWN", "REQUIRES_HARDWARE"), repeat=length):
            checks = [{"id": f"c{i}", "outcome": w} for i, w in enumerate(words)]
            try:
                out["overall/" + ",".join(words)] = outcomes.overall(checks)
            except Exception as exc:  # a mutant may crash; that is a different verdict too
                out["overall/" + ",".join(words)] = f"raised {type(exc).__name__}"
    return out


def _verdict(contract, raw):
    try:
        doc, problems = contract.load_report(raw)
    except Exception as exc:
        return f"raised {type(exc).__name__}"
    if doc is None:
        return "rejected"
    # PF-1 predicates on an accepted document, so a mutant that accepts a bad document is caught even if the
    # reference also accepts (it does not, for these inputs; this keeps the predicate explicit).
    ok = doc.get("hardware_verified") is False and all(
        c.get("outcome") == "REQUIRES_HARDWARE" for c in doc["checks"] if c.get("id") == "jetson.gpu")
    return "accepted" if ok else "accepted-but-PF-1-broken"


def main():
    check_headline_lines()
    sources = {name: (SRC / name).read_text(encoding="utf-8") for name in ("contract.py", "outcomes.py")}
    reference_outcomes = load_module("outcomes", sources["outcomes.py"])
    reference_contract = load_module("contract", sources["contract.py"])
    reference = verdicts(reference_contract, reference_outcomes)
    print(f"reference verdicts over {len(reference)} inputs")
    survivors, killed = [], []
    for filename, source in sources.items():
        for description, line, mutated in mutants_of(filename, source):
            try:
                if filename == "contract.py":
                    got = verdicts(load_module("contract", mutated), reference_outcomes)
                else:
                    got = verdicts(reference_contract, load_module("outcomes", mutated))
            except Exception as exc:
                got = {"load": f"raised {type(exc).__name__}"}
            differing = [k for k in reference if got.get(k) != reference[k]]
            # Prefer, as the witness, an input the mutant accepts but the shipped reader rejects: that is the
            # direction that matters (a weaker reader), rather than a valid fixture the mutant now refuses.
            wrongly_accepted = [k for k in differing if str(got.get(k)).startswith("accepted")
                                and reference[k] == "rejected"]
            tag = "headline" if line in HEADLINE[filename] else "other"
            if differing:
                killed.append((filename, description, tag, (wrongly_accepted or differing)[0], len(differing)))
            else:
                survivors.append((filename, description, tag))
    for filename, description, tag, first, n in killed:
        print(f"killed    {filename:12} {description:45} [{tag}] by {first} (+{n - 1} more)")
    for filename, description, tag in survivors:
        print(f"SURVIVED  {filename:12} {description:45} [{tag}]")
    headline_survivors = [s for s in survivors if s[2] == "headline"]
    print(f"{len(killed)} killed, {len(survivors)} survived, {len(headline_survivors)} headline survivors")
    return 1 if headline_survivors else 0


if __name__ == "__main__":
    sys.exit(main())
