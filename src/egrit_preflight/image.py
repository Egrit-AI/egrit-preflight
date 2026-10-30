"""image: inspect an image reference without pulling or running it, and compare it with an optional target record."""

import hashlib
import re

from . import outcomes as o
from . import safe
from .runner import run as default_run

REF_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._\-/:]{0,254}(@sha256:[0-9a-f]{64})?")
DIGEST_RE = re.compile(r"@(sha256:[0-9a-f]{64})\Z")
# Only these image environment variables are read; the rest may hold secrets and is never copied into a report.
ENV_KEYS = ("CUDA_VERSION", "NV_CUDA_LIB_VERSION", "CUDNN_VERSION", "NV_CUDNN_VERSION", "TENSORRT_VERSION",
            "NV_TENSORRT_VERSION", "L4T_VERSION", "JETPACK_VERSION", "NVIDIA_VISIBLE_DEVICES",
            "NVIDIA_DRIVER_CAPABILITIES")
# Labels are copied only when their key is a vendor version hint or one of a few provenance keys; values are clipped.
# Free-text labels such as description, source or url are never copied: they can hold internal URLs or tokens.
LABEL_HINTS = ("l4t", "jetpack", "cuda", "tensorrt")
OCI_LABELS = ("org.opencontainers.image.version", "org.opencontainers.image.revision",
              "org.opencontainers.image.created", "org.opencontainers.image.base.name",
              "org.opencontainers.image.base.digest")
ENV_VALUE_RE = re.compile(r"[A-Za-z0-9._+:,~-]{0,64}")
UNSET = ("", "not established", "unknown", None)
SHA_RE = re.compile(r"sha256:[0-9a-f]{64}")
ATTESTATION_TYPE = "attestation-manifest"
PREDICATE_KEY = "in-toto.io/predicate-type"
MAX_ATTESTATION_FETCHES = 4
TAG_ARTIFACT_SUFFIXES = ("sbom", "att", "sig", "vex")  # REPO:sha256-<hex>.<suffix>, the sigstore tag convention


def valid_reference(ref):
    return isinstance(ref, str) and bool(REF_RE.fullmatch(ref))


def version_tuple(text):
    """Up to six numeric components of at most nine digits (a longer run is not a version)."""
    m = re.match(r"\D*(\d{1,9}(?:\.\d{1,9}){0,5})(?!\d)", str(text or "")[:200])
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def load_target(path):
    """Read a target record. Returns (record, error)."""
    try:
        rec = safe.loads(safe.read_small_file(path).decode("utf-8"))
    except (OSError, ValueError) as e:
        return None, f"cannot read target record {safe.clean(path)}: {safe.clean(e)}"
    if rec is None:
        return None, "target record is not valid JSON"
    if not isinstance(rec, dict):
        return None, "target record must be a JSON object"
    return rec, None


def _get(rec, *keys):
    for k in keys:
        rec = rec.get(k) if isinstance(rec, dict) else None
    return None if rec in UNSET else rec


def l4t_from_reference(ref):
    """An L4T release such as r36.4.0 in the tag of an l4t image. Declared by the tag, not observed."""
    name, _, tag = ref.split("@")[0].rpartition(":")
    if "l4t" not in name.lower():
        return ()
    m = re.search(r"r(\d+)\.(\d+)(?:\.(\d+))?", tag)
    return tuple(int(g) for g in m.groups() if g is not None) if m else ()


def inspect_image(ref, target_path=None, require_digest=False, runner=default_run):
    checks = []
    result = {"reference": ref, "digest": None, "architecture": None, "platforms": None,
              "declared_dependencies": {}, "target": None}

    if not valid_reference(ref):
        checks.append(o.check("reference.valid", o.FAIL, "Not a valid image reference.",
                              detail=repr(ref)[:120], remediation="Use name[:tag][@sha256:<64 hex digits>]."))
        return {**result, "checks": checks}
    checks.append(o.check("reference.valid", o.PASS, "Image reference is well formed.", evidence=o.OBSERVED))

    m = DIGEST_RE.search(ref)
    result["digest"] = m.group(1) if m else None
    if m:
        checks.append(o.check("reference.pinned", o.PASS, "Reference is pinned by digest.", evidence=o.OBSERVED))
    else:
        checks.append(o.check(
            "reference.pinned", o.FAIL if require_digest else o.UNKNOWN,
            "Reference is a mutable tag, so the result is not reproducible.",
            remediation="Resolve a digest: docker buildx imagetools inspect " + ref + " ; then use name@sha256:<digest>."))

    target, terr = (None, None)
    if target_path:
        target, terr = load_target(target_path)
        if terr:
            checks.append(o.check("target.record", o.FAIL, "Target record unusable.", detail=terr))
    result["target"] = None if not target else {
        "name": safe.as_str(target.get("name")), "status": safe.as_str(target.get("status"), 40),
        "jetpack": safe.as_str(_get(target, "software", "jetpack"), 40),
        "jetson_linux": safe.as_str(_get(target, "software", "jetson_linux"), 40)}

    index = _inspect_manifest(ref, result, checks, runner)
    if index is None and result.get("source") == "local image":
        index = _fetch_index(ref, runner)
    _provenance(ref, index, result, checks, runner)
    _compare_target(ref, target, bool(target_path) and not terr, result, checks)
    checks.append(o.check(
        "jetson.gpu", o.REQUIRES_HARDWARE,
        "Whether this image's CUDA/TensorRT user space works on a Jetson GPU needs a physical device.",
        detail="An inspected manifest or an ARM64 smoke test is not Jetson, CUDA or TensorRT compatibility."))
    result["checks"] = checks
    return result


def _inspect_manifest(ref, result, checks, runner):
    r, data = None, None
    # With the containerd image store, inspecting an index digest names no architecture; ask for the arm64 variant.
    for extra in ([], ["--platform", "linux/arm64"]):
        r = runner(["docker", "image", "inspect", *extra, ref], 30)
        data = None
        if r.returncode == 0:
            docs = safe.loads(r.stdout)
            data = docs[0] if isinstance(docs, list) and docs and isinstance(docs[0], dict) else None
        if data and isinstance(data.get("Architecture"), str) and data["Architecture"]:
            break
        data = None
    if data:
        result["architecture"] = data["Architecture"].replace("aarch64", "arm64")
        if not result["digest"]:
            rd = [d.split("@")[1] for d in _list(data.get("RepoDigests")) if isinstance(d, str) and "@" in d]
            result["digest"] = rd[0] if rd and SHA_RE.fullmatch(rd[0]) else None
        result["declared_dependencies"] = _declared(data.get("Config"))
        result["source"] = "local image"
        checks.append(o.check("image.manifest", o.PASS, "Image found locally and inspected.",
                              evidence=o.OBSERVED, command=_brief(r)))
        _arch_check(result, checks)
        return None
    r2 = runner(["docker", "buildx", "imagetools", "inspect", "--raw", ref], 60)
    if r2.returncode != 0:
        checks.append(o.check(
            "image.manifest", o.UNKNOWN, "Image could not be inspected locally or in its registry.",
            detail=(r2.stderr or r.stderr).strip()[-300:] or "no output",
            remediation="Check the reference, your network and registry login; or 'docker pull --platform linux/arm64 "
                        + ref + "' and run again.", command=_brief(r2)))
        checks.append(o.check("image.architecture", o.UNKNOWN, "Architecture not established."))
        return None
    result["source"] = "registry manifest"
    raw = r2.stdout
    doc = safe.loads(raw)
    if not isinstance(doc, dict):
        doc = {}
    if not result["digest"]:
        result["digest"] = "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
        result["digest_note"] = "digest of the manifest document as served for this reference"
    manifests = doc.get("manifests") if isinstance(doc, dict) else None
    if manifests and isinstance(manifests, list):
        plats = []
        for mf in manifests:
            p = mf.get("platform") if isinstance(mf, dict) else None
            if not isinstance(p, dict) or not all(isinstance(p.get(k), str) for k in ("os", "architecture")):
                continue
            if p["os"] and p["architecture"] and p["os"] != "unknown":
                variant = p.get("variant") if isinstance(p.get("variant"), str) else ""
                plats.append("/".join(x for x in (p["os"], p["architecture"], variant) if x))
        result["platforms"] = sorted(set(plats))
        checks.append(o.check("image.manifest", o.PASS, "Registry manifest list inspected (nothing pulled).",
                              evidence=o.OBSERVED, command=_brief(r2)))
        if "linux/arm64" in plats or any(p.startswith("linux/arm64/") for p in plats):
            result["architecture"] = "arm64"
        elif plats:
            result["architecture"] = "no-arm64-variant"
        _arch_check(result, checks)
    else:
        # NVIDIA's L4T images are single-platform: the manifest names no architecture, its config does.
        cfg, cmd = _registry_config(ref, runner)
        if cfg:
            checks.append(o.check("image.manifest", o.PASS,
                                  "Single-platform manifest and its image config inspected (nothing pulled).",
                                  evidence=o.OBSERVED, command=cmd))
            result["architecture"] = cfg["architecture"].replace("aarch64", "arm64")
            result["declared_dependencies"] = _declared(cfg.get("config"))
            _arch_check(result, checks)
        else:
            checks.append(o.check("image.manifest", o.PASS, "Single-platform manifest inspected (nothing pulled).",
                                  evidence=o.OBSERVED, command=_brief(r2)))
            checks.append(o.check("image.architecture", o.UNKNOWN,
                                  "Single-platform manifest does not state its architecture here, and its image "
                                  "config could not be read.",
                                  remediation="Pull it with --platform linux/arm64 and inspect it locally.",
                                  command=cmd))
    return doc if isinstance(doc, dict) else None


def _declared(cfg):
    """Version-bearing env entries and labels from an image config's Config section (local or OCI shape)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    env = dict(e.split("=", 1) for e in _list(cfg.get("Env")) if isinstance(e, str) and "=" in e)
    deps = {k: env[k] for k in ENV_KEYS if k in env and ENV_VALUE_RE.fullmatch(env[k])}
    raw_labels = cfg.get("Labels") if isinstance(cfg.get("Labels"), dict) else {}
    labels = {k: safe.as_str(v, 100) for k, v in raw_labels.items()
              if isinstance(k, str) and isinstance(v, str)
              and (k in OCI_LABELS or any(h in k.lower() for h in LABEL_HINTS))}
    return {"env": deps, "labels": labels}


def _registry_config(ref, runner):
    """The image config a registry manifest points to: a small JSON document, not a layer. Nothing is pulled.

    `docker buildx imagetools inspect --format '{{json .Image}}'` prints the OCI config (architecture, os,
    config.Env, config.Labels). When it prints a map keyed by platform instead, the linux/arm64 entry is taken, or
    the only entry. Returns (config, command), with config None when nothing usable came back.
    """
    r = runner(["docker", "buildx", "imagetools", "inspect", "--format", "{{json .Image}}", ref], 60)
    doc = safe.loads(r.stdout) if r.returncode == 0 else None
    if isinstance(doc, dict) and not isinstance(doc.get("architecture"), str):
        entries = {k: v for k, v in doc.items() if isinstance(k, str) and isinstance(v, dict)}
        arm = [v for k, v in entries.items() if k == "linux/arm64" or k.startswith("linux/arm64/")]
        doc = arm[0] if arm else (next(iter(entries.values())) if len(entries) == 1 else None)
    if isinstance(doc, dict) and isinstance(doc.get("architecture"), str) and doc["architecture"]:
        return doc, _brief(r)
    return None, _brief(r)


def repo_name(ref):
    """The repository part of a reference: no digest, no tag (a registry port is not a tag)."""
    name = ref.split("@")[0]
    head, _, last = name.rpartition("/")
    return (head + "/" if head else "") + last.split(":")[0]


def classify_predicate(predicate_type):
    t = (predicate_type or "").lower()
    if "spdx" in t or "cyclonedx" in t:
        return "sbom"
    if "slsa.dev/provenance" in t:
        return "provenance"
    return "other"


def _fetch_index(ref, runner):
    """Best-effort registry manifest list for a locally present image. Metadata only; no layers."""
    r = runner(["docker", "buildx", "imagetools", "inspect", "--raw", ref], 60)
    if r.returncode != 0:
        return None
    doc = safe.loads(r.stdout)
    return doc if isinstance(doc, dict) else None


def _provenance(ref, index, result, checks, runner):
    """SBOM and build-provenance attestations that the registry lists for the linux/arm64 image.

    Presence is a declaration by the publisher. Nothing here reads an attestation's contents or verifies a signature.
    """
    prov = {"signature_verified": False, "attestations": [], "arm64_manifest_digests": [], "errors": []}
    result["provenance"] = prov

    def unknown(why, remediation=None):
        for cid, what in (("image.sbom", "SBOM attestation"), ("image.provenance", "Build provenance attestation")):
            checks.append(o.check(cid, o.UNKNOWN, f"{what} not established: {why}", remediation=remediation))

    manifests = index.get("manifests") if isinstance(index, dict) else None
    if not isinstance(manifests, list) or not manifests:
        prov["status"] = "no-manifest-list"
        if _tag_artifacts(ref, result, prov, checks, runner):
            return None
        return unknown("no registry manifest list was available for this reference.")
    arm64 = set()
    for mf in manifests:
        p = (mf.get("platform") if isinstance(mf, dict) else None) or {}
        if isinstance(p, dict) and p.get("os") == "linux" and p.get("architecture") == "arm64" and _is_digest(mf.get("digest")):
            arm64.add(mf["digest"])
    prov["arm64_manifest_digests"] = sorted(arm64)
    if not arm64:
        prov["status"] = "no-arm64-manifest"
        return unknown("the manifest list has no linux/arm64 image.")
    entries = []
    for mf in manifests:
        a = (mf.get("annotations") if isinstance(mf, dict) else None) or {}
        subject = a.get("vnd.docker.reference.digest") if isinstance(a, dict) else None
        if (isinstance(subject, str) and subject in arm64 and a.get("vnd.docker.reference.type") == ATTESTATION_TYPE
                and _is_digest(mf.get("digest"))):
            entries.append((mf["digest"], subject))
    if not entries:
        prov["status"] = "none-published"
        if _tag_artifacts(ref, result, prov, checks, runner):
            return None
        return unknown("the registry lists no attestation for the linux/arm64 image.",
                       "Ask the publisher for an SBOM and provenance, or generate your own at build time.")
    repo = repo_name(ref)
    kinds = {}
    for att_digest, subject in entries[:MAX_ATTESTATION_FETCHES]:
        r = runner(["docker", "buildx", "imagetools", "inspect", "--raw", f"{repo}@{att_digest}"], 60)
        doc = safe.loads(r.stdout) if r.returncode == 0 else None
        layers = doc.get("layers") if isinstance(doc, dict) else None
        if not isinstance(layers, list):
            prov["errors"].append(f"attestation manifest {att_digest} could not be read")
            continue
        types = sorted({a.get(PREDICATE_KEY) for a in
                        ((l.get("annotations") if isinstance(l, dict) else None) for l in layers)
                        if isinstance(a, dict) and isinstance(a.get(PREDICATE_KEY), str)})
        prov["attestations"].append({"attestation_manifest_digest": att_digest, "subject_digest": subject,
                                     "predicate_types": types})
        for t in types:
            kinds.setdefault(classify_predicate(t), []).append(t)
    if len(entries) > MAX_ATTESTATION_FETCHES:
        prov["errors"].append(f"only the first {MAX_ATTESTATION_FETCHES} of {len(entries)} attestations were read")
    prov["status"] = "listed" if prov["attestations"] else "unreadable"
    note = "Its contents and any signature were not verified; a digest fixes content, not who published it."
    for cid, kind, what in (("image.sbom", "sbom", "SBOM"), ("image.provenance", "provenance", "Build provenance")):
        if kinds.get(kind):
            checks.append(o.check(cid, o.PASS, f"{what} attestation ({', '.join(sorted(set(kinds[kind])))}) is "
                                  f"listed for the linux/arm64 image. {note}", evidence=o.DECLARED,
                                  detail={"attestations": prov["attestations"]}))
        elif prov["attestations"]:
            checks.append(o.check(cid, o.UNKNOWN, f"{what} attestation not found among the listed attestations.",
                                  detail={"predicate_types": sorted({t for a in prov["attestations"]
                                                                     for t in a["predicate_types"]})}))
        else:
            checks.append(o.check(cid, o.UNKNOWN, f"{what} attestation listed but unreadable.",
                                  detail="; ".join(prov["errors"])))


def _tag_artifacts(ref, result, prov, checks, runner):
    """SBOM, attestation, signature and VEX artefacts published as digest-named tags, the sigstore convention.

    NVIDIA's l4t images list `REPO:sha256-<hex>.sbom`, `.sig` and `.vex` tags for each digest instead of BuildKit
    attestation manifests. Only each tag's manifest is read, never its contents; nothing is pulled and nothing is
    verified. Writes the two checks and returns True when at least one such tag exists, else changes nothing.
    """
    digest = result.get("digest")
    if not _is_digest(digest):
        return False
    repo = repo_name(ref)
    found = {}
    for suffix in TAG_ARTIFACT_SUFFIXES:
        tag = f"{repo}:{digest.replace(':', '-')}.{suffix}"
        r = runner(["docker", "buildx", "imagetools", "inspect", "--raw", tag], 60)
        if r.returncode == 0 and isinstance(safe.loads(r.stdout), dict):
            found[suffix] = tag
    if not found:
        return False
    prov["tag_artifacts"] = found
    for suffix in ("sbom", "att"):
        if suffix in found:
            prov["attestations"].append({"tag": found[suffix], "subject_digest": digest, "predicate_types": [],
                                         "style": "digest-named tag"})
    prov["status"] = "listed" if prov["attestations"] else "none-published"
    note = "Its contents and any signature were not verified; a digest fixes content, not who published it."
    listed = {"tags": sorted(found.values()), "signature_tag": found.get("sig")}
    if "sbom" in found:
        checks.append(o.check("image.sbom", o.PASS,
                              f"SBOM is listed by the publisher as a digest-named tag for this image. {note}",
                              evidence=o.DECLARED, detail=listed))
    else:
        checks.append(o.check("image.sbom", o.UNKNOWN, "SBOM attestation not established: the publisher lists "
                              "digest-named tags for this image, none of them an SBOM.", detail=listed))
    if "att" in found:
        checks.append(o.check("image.provenance", o.UNKNOWN, "Build provenance attestation not established: an "
                              "attestation bundle (.att) is listed for this image and its predicate type was not read.",
                              detail=listed))
    else:
        checks.append(o.check("image.provenance", o.UNKNOWN, "Build provenance attestation not established: the "
                              "publisher lists digest-named tags for this image, none of them an attestation bundle.",
                              detail=listed))
    return True


def _arch_check(result, checks):
    a = result["architecture"]
    if a == "arm64":
        checks.append(o.check("image.architecture", o.PASS, "Image provides linux/arm64.", evidence=o.OBSERVED,
                              detail={"platforms": result["platforms"]} if result["platforms"] else None))
    elif a:
        checks.append(o.check(
            "image.architecture", o.FAIL, f"Architecture mismatch: image is {a}, target is arm64.",
            evidence=o.OBSERVED, detail={"platforms": result["platforms"]} if result["platforms"] else None,
            remediation="Use or build an image that provides linux/arm64 (docker buildx build --platform linux/arm64)."))
    else:
        checks.append(o.check("image.architecture", o.UNKNOWN, "Architecture not established."))


ARM64_NAMES = ("aarch64", "arm64")


def _target_architecture(target, checks):
    """Compare the architecture a target record declares with linux/arm64. No check when the record states none."""
    declared = _get(target, "architecture")
    if declared is None:
        return
    shown = safe.as_str(declared, 40) or "a value that is not text"
    if isinstance(declared, str) and declared.strip().lower() in ARM64_NAMES:
        checks.append(o.check("target.architecture", o.PASS,
                              f"Target declares {shown}, which this report covers (linux/arm64). Declared, not observed "
                              "on a device.", evidence=o.DECLARED))
    else:
        checks.append(o.check(
            "target.architecture", o.FAIL,
            f"Target declares architecture {shown}. This report is about linux/arm64 only and says nothing about it.",
            evidence=o.DECLARED,
            remediation="Use this tool only for linux/arm64 (aarch64) targets; its results do not carry over."))


def _compare_target(ref, target, target_ok, result, checks):
    deps_env = result["declared_dependencies"].get("env", {}) if result["declared_dependencies"] else {}
    grade = o.DECLARED  # target records and image tags are declarations until read from a device
    if not target_ok:
        if target is None and not result["target"]:
            why = "No target record supplied (--target)."
            fix = ("Pass a target record for your JetPack release, such as --target examples/targets/jetpack-6.2.json "
                   "(one per release in examples/targets/), or a copy edited to match your device.")
        else:
            why, fix = "Target record unusable.", "Fix the target record (see target.record) and run again."
        for cid, what in (("target.jetpack", "JetPack version"), ("target.l4t", "L4T agreement"),
                          ("runtime.cuda", "CUDA version"), ("runtime.tensorrt", "TensorRT version")):
            checks.append(o.check(cid, o.UNKNOWN, f"{what} not compared. {why}", remediation=fix))
        return

    _target_architecture(target, checks)
    jp = _get(target, "software", "jetpack")
    jl = _get(target, "software", "jetson_linux")
    if jp is None:
        checks.append(o.check("target.jetpack", o.UNKNOWN, "Target record does not state a JetPack version.",
                              remediation="Add software.jetpack to the target record."))
    else:
        checks.append(o.check("target.jetpack", o.PASS, f"Target JetPack {jp} (as declared in the record).",
                              evidence=grade))

    img_l4t = l4t_from_reference(ref) or version_tuple(deps_env.get("L4T_VERSION"))
    tgt_l4t = version_tuple(jl)
    if not tgt_l4t:
        checks.append(o.check("target.l4t", o.UNKNOWN, "Target record does not state a Jetson Linux (L4T) version.",
                              remediation="Add software.jetson_linux to the target record."))
    elif not img_l4t:
        nr = _not_read(result, ref, "L4T release (the tag states none and)")
        if nr:
            checks.append(o.check("target.l4t", o.UNKNOWN, nr[0], remediation=nr[1]))
        else:
            checks.append(o.check("target.l4t", o.UNKNOWN, "Image does not declare an L4T release.",
                                  remediation="Use an image whose tag states its L4T release (rNN.N.N) or whose "
                                              "environment sets L4T_VERSION."))
    elif img_l4t[0] != tgt_l4t[0]:
        checks.append(o.check("target.l4t", o.FAIL,
                              f"L4T major mismatch: image r{'.'.join(map(str, img_l4t))}, target {jl}.",
                              evidence=grade))
    elif img_l4t[:2] != tgt_l4t[:2]:
        checks.append(o.check("target.l4t", o.UNKNOWN,
                              f"L4T minor differs: image r{'.'.join(map(str, img_l4t))}, target {jl}. "
                              "Compatibility rules are not assessed here.", evidence=grade))
    else:
        checks.append(o.check("target.l4t", o.PASS,
                              f"Declared L4T release agrees at major.minor (image r{'.'.join(map(str, img_l4t))}, "
                              f"target {jl}). Declared, not observed on a device.", evidence=grade))

    for cid, label, keys, tkey in (("runtime.cuda", "CUDA", ("CUDA_VERSION", "NV_CUDA_LIB_VERSION"), "cuda"),
                                   ("runtime.tensorrt", "TensorRT", ("TENSORRT_VERSION", "NV_TENSORRT_VERSION"),
                                    "tensorrt")):
        want = version_tuple(_get(target, "runtimes", tkey))
        have = next((version_tuple(deps_env[k]) for k in keys if k in deps_env and version_tuple(deps_env[k])), ())
        if not have:
            nr = _not_read(result, ref, f"{label} version")
            if nr:
                checks.append(o.check(cid, o.UNKNOWN, nr[0], remediation=nr[1]))
            else:
                checks.append(o.check(cid, o.UNKNOWN, f"Image declares no {label} version."))
        elif not want:
            checks.append(o.check(cid, o.UNKNOWN, f"Target record states no {label} version.",
                                  remediation=f"Add runtimes.{tkey} to the target record."))
        elif have[0] != want[0]:
            checks.append(o.check(cid, o.FAIL,
                                  f"Unsupported dependency: image declares {label} {'.'.join(map(str, have))}, "
                                  f"target offers {'.'.join(map(str, want))}.", evidence=grade))
        else:
            checks.append(o.check(cid, o.REQUIRES_HARDWARE,
                                  f"Declared {label} versions agree at major version; whether the device libraries "
                                  "satisfy the image needs a physical Jetson.", evidence=grade))


def _not_read(result, ref, what):
    """Why a declared value went unread on this host: (summary, remediation), or None when the image was read locally.

    Declared dependencies come from the image config. A bare registry manifest, or no inspection at all, never
    shows them, so "declares no CUDA version" would be a claim about an environment nobody read.
    """
    if result["declared_dependencies"]:
        return None  # the image config was read, locally or from the registry, so "declares none" is a fact
    if result.get("source") == "registry manifest":
        return (f"{what} not read from the registry manifest; declared dependencies are read from a local image only.",
                f"'docker pull --platform linux/arm64 {ref}' and run again.")
    return (f"{what} not read: the image could not be inspected (see image.manifest).",
            "Make the image inspectable locally or in its registry (see image.manifest) and run again.")


def _list(value):
    return value if isinstance(value, list) else []


def _is_digest(value):
    return isinstance(value, str) and bool(SHA_RE.fullmatch(value))


def _brief(r):
    return {"argv": list(r.argv), "returncode": r.returncode}
