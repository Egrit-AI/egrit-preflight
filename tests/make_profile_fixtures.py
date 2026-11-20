"""Builds the vendor target profile fixtures. `python3 -m tests.make_profile_fixtures` rewrites tests/fixtures/profiles/.

Every profile here is synthetic: the vendor, products, revisions, versions and URLs are made up, the URLs are under the
reserved `.example` domain, and nothing was read from a vendor page or a device. The invalid fixtures are the complete
profile with one thing broken. tests/test_profile.py fails if the committed files differ from what this module
produces.
"""

import copy
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "profiles"
DOCUMENT = "egrit-preflight vendor target profile"
FACTS = ("architecture", "os_distribution", "os_build", "abi", "jetpack", "jetson_linux", "cuda", "tensorrt",
         "container_runtime")
SOURCE = "https://vendor.example/edge-one/software-1.4.0"
DATE = "2026-11-18"
VALUES = {"architecture": "aarch64", "os_distribution": "Example Linux 4 (Yocto based)", "os_build": "el4-20261001",
          "abi": "glibc 2.39", "jetpack": "6.2", "jetson_linux": "36.4.3", "cuda": "12.6.10", "tensorrt": "10.3.0",
          "container_runtime": "containerd 1.7.27"}


def identity(product="Edge One", model="E1-16", module="jetson-orin-nx-16gb", hardware="B", software="1.4.0",
             revision="1"):
    return {"vendor": "Example Vendor (synthetic)", "product": product, "model": model, "module": module,
            "hardware_revision": hardware, "software_revision": software, "profile_revision": revision}


def statement(value, hardware="B", software="1.4.0", evidence="declared", url=SOURCE, date=DATE):
    return {"value": value, "evidence": evidence, "source_url": url, "retrieved": date,
            "applies_to": {"hardware_revision": hardware, "software_revision": software}}


def nothing(hardware="B", software="1.4.0"):
    return statement(None, hardware, software, evidence="none", url=None, date=None)


def profile(ident=None, values=None, **statement_args):
    values = VALUES if values is None else values
    ident = ident or identity()
    return {"document": DOCUMENT, "profile_version": "1", "synthetic": True, "identity": ident,
            "facts": {f: [statement(values[f], **statement_args)] if f in values else [] for f in FACTS},
            "required_interfaces": ["csi-camera", "gpu"]}


def valid():
    out = {"complete-declared": profile()}

    # The vendor page says "JetPack 6" and names no software or hardware revision.
    family_only = profile(identity(hardware=None, software=None), {"architecture": "aarch64", "jetpack": "6"},
                          hardware=None, software=None)
    out["missing-software-revision"] = family_only

    contradictory = profile()
    contradictory["facts"]["jetpack"].append(statement("6.1", url="https://vendor.example/edge-one/datasheet"))
    out["contradictory-jetpack"] = contradictory

    out["wrong-architecture"] = profile(values=dict(VALUES, architecture="x86_64"))
    out["abi-absent"] = profile(values={k: v for k, v in VALUES.items() if k != "abi"})

    other = profile(identity(hardware="A"), hardware="B")
    out["other-revision-only"] = other

    sibling = profile(identity(product="Edge Two", model=None, module=None, hardware=None, software=None), {})
    sibling["facts"] = {f: [nothing(None, None)] for f in FACTS}
    sibling["required_interfaces"] = []
    out["sibling-product-nothing-stated"] = sibling

    out["later-software-revision"] = profile(identity(software="1.5.0"), dict(VALUES, jetpack="6.2.1",
                                                                              jetson_linux="36.4.4"),
                                             software="1.5.0")

    scoped = profile(identity(hardware="C"), hardware="C")
    scoped["equivalences"] = [{"identity": identity(), "fields": ["jetpack", "jetson_linux"], "evidence": "declared",
                               "source_url": "https://vendor.example/edge-one/revision-c-notice", "retrieved": DATE}]
    out["equivalence-scoped-to-two-fields"] = scoped

    out["observed-statements"] = profile(evidence="observed", url=None)
    return out


def invalid():
    def broken(edit):
        doc = copy.deepcopy(profile())
        edit(doc)
        return json.dumps(doc, indent=2) + "\n"

    def fact(name, **changes):
        return lambda d: d["facts"][name][0].update(changes)

    equivalence = {"identity": identity(hardware="C"), "fields": ["jetpack"], "evidence": "declared",
                   "source_url": SOURCE, "retrieved": DATE}

    def omitted_source(d):
        d["facts"]["jetpack"][0].update(evidence="observed", source_url=None)
        del d["facts"]["jetpack"][0]["source_url"]

    return {
        "not-an-object": "[]\n",
        "truncated": json.dumps(profile(), indent=2)[:200],
        "nan-constant": broken(lambda d: d.update(note="x")).replace('"x"', "NaN"),
        "wrong-document": broken(lambda d: d.update(document="egrit-preflight target assessment")),
        "unsupported-version": broken(lambda d: d.update(profile_version="2")),
        "identity-field-missing": broken(lambda d: d["identity"].pop("software_revision")),
        "identity-vendor-empty": broken(lambda d: d["identity"].update(vendor="")),
        "fact-missing": broken(lambda d: d["facts"].pop("abi")),
        "fact-unknown": broken(lambda d: d["facts"].update(jetpak=[])),
        "value-without-evidence": broken(fact("jetpack", evidence="none")),
        "value-declared-without-source": broken(fact("jetpack", source_url=None)),
        "value-declared-without-date": broken(fact("jetpack", retrieved=None)),
        "value-observed-without-date": broken(fact("jetpack", evidence="observed", source_url=None, retrieved=None)),
        "observed-source-key-missing": broken(omitted_source),
        "null-value-claimed-declared": broken(fact("jetpack", value=None)),
        "not-established-written-as-a-value": broken(fact("jetpack", value="not established")),
        "evidence-verified": broken(fact("jetpack", evidence="verified")),
        "source-not-https": broken(fact("jetpack", source_url="http://vendor.example/page")),
        "date-not-iso": broken(fact("jetpack", retrieved="18 November 2026")),
        "applies-to-missing": broken(lambda d: d["facts"]["jetpack"][0].pop("applies_to")),
        "applies-to-without-software-revision":
            broken(lambda d: d["facts"]["jetpack"][0]["applies_to"].pop("software_revision")),
        "value-control-characters": broken(fact("jetpack", value="6.2\u001b[2J")),
        "interface-bad-name": broken(lambda d: d.update(required_interfaces=["GPU works"])),
        "interfaces-missing": broken(lambda d: d.pop("required_interfaces")),
        "equivalence-without-source": broken(lambda d: d.update(equivalences=[dict(equivalence, source_url=None)])),
        "equivalence-partial-identity":
            broken(lambda d: d.update(equivalences=[dict(equivalence, identity=identity(hardware=None))])),
        "equivalence-without-fields": broken(lambda d: d.update(equivalences=[dict(equivalence, fields=[])])),
    }


def build():
    files = {f"valid/{name}.json": json.dumps(doc, indent=2) + "\n" for name, doc in valid().items()}
    files.update({f"invalid/{name}.json": text for name, text in invalid().items()})
    return files


def main():
    for folder in ("valid", "invalid"):
        (FIXTURES / folder).mkdir(parents=True, exist_ok=True)
        for old in (FIXTURES / folder).glob("*.json"):
            old.unlink()
    for name, text in build().items():
        (FIXTURES / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(build())} profile fixtures to {FIXTURES}")


if __name__ == "__main__":
    main()
