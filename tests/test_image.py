import json
import re
import tempfile
import unittest
from pathlib import Path

from egrit_preflight.image import (classify_predicate, inspect_image, l4t_from_reference, repo_name, valid_reference,
                                   version_tuple)
from tests.fakes import DIGEST, FakeRunner, bad, image_inspect, ok

PINNED = f"ubuntu@{DIGEST}"


def by_id(r, cid):
    return next(c for c in r["checks"] if c["id"] == cid)


def target(**software):
    d = tempfile.mkdtemp()
    p = Path(d) / "t.json"
    rec = {"name": "orin", "status": "declared", "software": software.get("software", {}),
           "runtimes": software.get("runtimes", {})}
    p.write_text(json.dumps(rec))
    return str(p)


def local(arch="arm64", env=None):
    return FakeRunner([(("docker", "image", "inspect"), ok(image_inspect(arch, env)))])


def single_platform(config_answer):
    """No local image; the registry answers --raw with a single-platform manifest and --format with config_answer."""
    def imagetools(argv):
        return config_answer if "--format" in argv else ok(json.dumps({"schemaVersion": 2, "config": {"digest": "x"}}))
    return FakeRunner([(("docker", "image", "inspect"), bad("No such image")),
                       (("docker", "buildx", "imagetools"), imagetools)])


class Image(unittest.TestCase):
    def test_invalid_references_fail_and_run_nothing(self):
        for bad_ref in ("", "-v /:/host", "ubuntu 24.04", "UBUNTU;rm", "a" * 300, "x@sha256:short"):
            fake = FakeRunner([])
            r = inspect_image(bad_ref, runner=fake)
            self.assertEqual(r["checks"][0]["outcome"], "FAIL", bad_ref)
            self.assertEqual(fake.calls, [], bad_ref)

    def test_arm64_pinned_local(self):
        r = inspect_image(PINNED, runner=local())
        self.assertEqual(r["digest"], DIGEST)
        self.assertEqual(by_id(r, "image.architecture")["outcome"], "PASS")
        self.assertEqual(by_id(r, "reference.pinned")["outcome"], "PASS")

    def test_architecture_mismatch_fails(self):
        r = inspect_image(PINNED, runner=local("amd64"))
        c = by_id(r, "image.architecture")
        self.assertEqual(c["outcome"], "FAIL")
        self.assertIn("mismatch", c["summary"])

    def test_mutable_tag_unknown_or_fail_with_flag(self):
        self.assertEqual(by_id(inspect_image("ubuntu:24.04", runner=local()), "reference.pinned")["outcome"], "UNKNOWN")
        self.assertEqual(by_id(inspect_image("ubuntu:24.04", require_digest=True, runner=local()),
                               "reference.pinned")["outcome"], "FAIL")

    def test_registry_manifest_list_without_arm64_fails(self):
        doc = {"manifests": [{"platform": {"os": "linux", "architecture": "amd64"}}]}
        fake = FakeRunner([(("docker", "image", "inspect"), bad("No such image")),
                           (("docker", "buildx", "imagetools"), ok(json.dumps(doc)))])
        r = inspect_image("ubuntu:24.04", runner=fake)
        self.assertEqual(by_id(r, "image.architecture")["outcome"], "FAIL")
        self.assertEqual(r["platforms"], ["linux/amd64"])
        self.assertTrue(r["digest"].startswith("sha256:"))
        self.assertFalse(any(c[:2] == ["docker", "pull"] for c in fake.calls), "image must never pull")

    def test_registry_manifest_list_with_arm64(self):
        doc = {"manifests": [{"platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}},
                             {"platform": {"os": "unknown", "architecture": "unknown"}}]}
        fake = FakeRunner([(("docker", "image", "inspect"), bad("No such image")),
                           (("docker", "buildx", "imagetools"), ok(json.dumps(doc)))])
        r = inspect_image(PINNED, runner=fake)
        self.assertEqual(by_id(r, "image.architecture")["outcome"], "PASS")
        self.assertEqual(r["platforms"], ["linux/arm64/v8"])

    def test_registry_unreachable_is_unknown(self):
        fake = FakeRunner([(("docker", "image", "inspect"), bad("No such image")),
                           (("docker", "buildx", "imagetools"), bad("dial tcp: no route to host"))])
        r = inspect_image(PINNED, runner=fake)
        self.assertEqual(by_id(r, "image.manifest")["outcome"], "UNKNOWN")
        self.assertEqual(by_id(r, "image.architecture")["outcome"], "UNKNOWN")

    def test_no_target_everything_unknown_never_pass(self):
        r = inspect_image(PINNED, runner=local())
        for cid in ("target.jetpack", "target.l4t", "runtime.cuda", "runtime.tensorrt"):
            self.assertEqual(by_id(r, cid)["outcome"], "UNKNOWN", cid)

    def test_missing_jetpack_version_unknown(self):
        r = inspect_image(PINNED, target(software={}), runner=local())
        self.assertEqual(by_id(r, "target.jetpack")["outcome"], "UNKNOWN")
        r = inspect_image(PINNED, target(software={"jetpack": "not established"}), runner=local())
        self.assertEqual(by_id(r, "target.jetpack")["outcome"], "UNKNOWN")

    def test_l4t_major_mismatch_fail_minor_unknown_match_declared_pass(self):
        t = target(software={"jetpack": "6.2", "jetson_linux": "36.4.3"})
        self.assertEqual(by_id(inspect_image("nvcr.io/nvidia/l4t-base:r35.4.1", t, runner=local()),
                               "target.l4t")["outcome"], "FAIL")
        self.assertEqual(by_id(inspect_image("nvcr.io/nvidia/l4t-base:r36.2.0", t, runner=local()),
                               "target.l4t")["outcome"], "UNKNOWN")
        c = by_id(inspect_image("nvcr.io/nvidia/l4t-base:r36.4.0", t, runner=local()), "target.l4t")
        self.assertEqual(c["outcome"], "PASS")
        self.assertEqual(c["evidence"], "declared")

    def test_unsupported_cuda_dependency_fails_matching_requires_hardware(self):
        t = target(software={"jetpack": "6.2"}, runtimes={"cuda": "12.6", "tensorrt": "10.3"})
        r = inspect_image(PINNED, t, runner=local(env=["CUDA_VERSION=11.4.1", "TENSORRT_VERSION=10.3.0"]))
        self.assertEqual(by_id(r, "runtime.cuda")["outcome"], "FAIL")
        self.assertEqual(by_id(r, "runtime.tensorrt")["outcome"], "REQUIRES_HARDWARE")
        r = inspect_image(PINNED, t, runner=local())
        self.assertEqual(by_id(r, "runtime.cuda")["outcome"], "UNKNOWN")

    def test_secrets_in_image_env_never_copied(self):
        r = inspect_image(PINNED, runner=local(env=["API_TOKEN=hunter2", "CUDA_VERSION=12.6.1"]))
        text = json.dumps(r)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("API_TOKEN", text)
        self.assertEqual(r["declared_dependencies"]["env"], {"CUDA_VERSION": "12.6.1"})

    def test_unreadable_target_record_fails(self):
        r = inspect_image(PINNED, "/no/such/file.json", runner=local())
        self.assertEqual(by_id(r, "target.record")["outcome"], "FAIL")

    def test_gpu_always_requires_hardware(self):
        self.assertEqual(by_id(inspect_image(PINNED, runner=local()), "jetson.gpu")["outcome"], "REQUIRES_HARDWARE")

    def test_index_digest_with_empty_local_architecture_asks_for_arm64_variant(self):
        # Seen on a real Docker with the containerd image store: inspecting an index digest names no architecture.
        fake = FakeRunner([(("docker", "image", "inspect", "--platform"), ok(image_inspect("arm64"))),
                           (("docker", "image", "inspect"), ok(image_inspect("")))])
        r = inspect_image(PINNED, runner=fake)
        self.assertEqual(by_id(r, "image.architecture")["outcome"], "PASS")
        self.assertEqual(r["source"], "local image")

    def test_empty_local_architecture_everywhere_falls_back_to_registry(self):
        doc = {"manifests": [{"platform": {"os": "linux", "architecture": "arm64"}}]}
        fake = FakeRunner([(("docker", "image", "inspect"), ok(image_inspect(""))),
                           (("docker", "buildx", "imagetools"), ok(json.dumps(doc)))])
        r = inspect_image(PINNED, runner=fake)
        self.assertEqual(by_id(r, "image.architecture")["outcome"], "PASS")
        self.assertEqual(r["source"], "registry manifest")

    def test_shipped_example_target_is_usable(self):
        ex = str(Path(__file__).resolve().parent.parent / "examples" / "target-orin-nano-jetpack-6.2.json")
        r = inspect_image("nvcr.io/nvidia/l4t-base:r36.4.0", ex, runner=local())
        self.assertEqual(by_id(r, "target.jetpack")["outcome"], "PASS")
        self.assertEqual(by_id(r, "target.jetpack")["evidence"], "declared")
        self.assertEqual(by_id(r, "target.l4t")["outcome"], "PASS")

    def test_no_target_unknowns_name_the_input_to_supply(self):
        # Prevents an UNKNOWN that leaves the user guessing: each no-target check names --target and the record library.
        r = inspect_image(PINNED, runner=local())
        for cid in ("target.jetpack", "target.l4t", "runtime.cuda", "runtime.tensorrt"):
            c = by_id(r, cid)
            self.assertEqual(c["outcome"], "UNKNOWN", cid)
            self.assertIn("--target examples/targets/jetpack-6.2.json", c["remediation"], cid)

    def test_registry_only_inspection_says_versions_were_not_read_and_how_to_pull(self):
        # Prevents "Image declares no CUDA version" from the registry path, which never reads the image's environment.
        doc = {"manifests": [{"platform": {"os": "linux", "architecture": "arm64"}}]}
        fake = FakeRunner([(("docker", "image", "inspect"), bad("No such image")),
                           (("docker", "buildx", "imagetools"), ok(json.dumps(doc)))])
        t = target(software={"jetpack": "6.2", "jetson_linux": "36.4.3"}, runtimes={"cuda": "12.6", "tensorrt": "10.3"})
        r = inspect_image("ubuntu:24.04", t, runner=fake)
        self.assertEqual(r["source"], "registry manifest")
        for cid in ("runtime.cuda", "runtime.tensorrt", "target.l4t"):
            c = by_id(r, cid)
            self.assertEqual(c["outcome"], "UNKNOWN", cid)
            self.assertIn("not read from the registry manifest", c["summary"], cid)
            self.assertIn("docker pull --platform linux/arm64 ubuntu:24.04", c["remediation"], cid)

    def test_local_image_without_versions_still_says_it_declares_none(self):
        # Prevents the registry wording leaking into the local path, where the environment really was read.
        t = target(software={"jetpack": "6.2", "jetson_linux": "36.4.3"}, runtimes={"cuda": "12.6"})
        c = by_id(inspect_image(PINNED, t, runner=local()), "runtime.cuda")
        self.assertEqual(c["summary"], "Image declares no CUDA version.")
        self.assertNotIn("remediation", c)
    def test_single_platform_manifest_reads_its_config_for_architecture_and_versions(self):
        # Prevents the registry path establishing nothing for NVIDIA's single-platform L4T images.
        cfg = {"architecture": "arm64", "os": "linux",
               "config": {"Env": ["CUDA_VERSION=12.6.1", "PATH=/usr/bin"], "Labels": {"org.opencontainers.image.version": "1"}}}
        fake = single_platform(ok(json.dumps(cfg)))
        r = inspect_image("nvcr.io/nvidia/l4t-jetpack:r36.4.0", runner=fake)
        self.assertEqual(r["source"], "registry manifest")
        self.assertEqual(by_id(r, "image.architecture")["outcome"], "PASS")
        self.assertEqual(by_id(r, "image.architecture")["evidence"], "observed")
        self.assertEqual(r["declared_dependencies"]["env"], {"CUDA_VERSION": "12.6.1"})
        self.assertEqual(by_id(r, "jetson.gpu")["outcome"], "REQUIRES_HARDWARE")
        self.assertFalse(any(c[:2] == ["docker", "pull"] for c in fake.calls))

    def test_single_platform_amd64_config_fails_like_the_local_path(self):
        # Prevents an amd64-only image reading as merely UNKNOWN once its config is in hand.
        r = inspect_image(PINNED, runner=single_platform(ok(json.dumps({"architecture": "amd64", "os": "linux"}))))
        c = by_id(r, "image.architecture")
        self.assertEqual(c["outcome"], "FAIL")
        self.assertIn("mismatch", c["summary"])

    def test_single_platform_unreadable_config_stays_unknown_with_remediation(self):
        # Prevents a failed config read turning into a claim either way.
        c = by_id(inspect_image(PINNED, runner=single_platform(bad("unsupported"))), "image.architecture")
        self.assertEqual(c["outcome"], "UNKNOWN")
        self.assertIn("remediation", c)

    def test_platform_keyed_config_map_takes_the_arm64_entry(self):
        # Prevents a map-shaped answer (what buildx prints for a list) reading as no config at all.
        doc = {"linux/amd64": {"architecture": "amd64", "os": "linux"},
               "linux/arm64": {"architecture": "arm64", "os": "linux", "config": {"Env": ["TENSORRT_VERSION=10.3.0"]}}}
        r = inspect_image(PINNED, runner=single_platform(ok(json.dumps(doc))))
        self.assertEqual(by_id(r, "image.architecture")["outcome"], "PASS")
        self.assertEqual(r["declared_dependencies"]["env"], {"TENSORRT_VERSION": "10.3.0"})

    def test_helpers(self):
        self.assertTrue(valid_reference("nvcr.io/nvidia/l4t-base:r36.2.0"))
        self.assertEqual(version_tuple("12.6.1-1"), (12, 6, 1))
        self.assertEqual(l4t_from_reference("nvcr.io/nvidia/l4t-base:r36.2.0"), (36, 2, 0))
        self.assertEqual(l4t_from_reference("ubuntu:r36.2.0"), ())


ARM = "sha256:" + "1" * 64
AMD = "sha256:" + "2" * 64
ATT_ARM = "sha256:" + "3" * 64
ATT_AMD = "sha256:" + "4" * 64
SPDX = "https://spdx.dev/Document"
SLSA = "https://slsa.dev/provenance/v0.2"


def plat(digest, arch):
    return {"digest": digest, "platform": {"os": "linux", "architecture": arch}}


def att(digest, subject, type_="attestation-manifest"):
    return {"digest": digest, "platform": {"os": "unknown", "architecture": "unknown"},
            "annotations": {"vnd.docker.reference.type": type_, "vnd.docker.reference.digest": subject}}


def att_doc(*predicates):
    return {"layers": [{"annotations": {"in-toto.io/predicate-type": p}} for p in predicates]}


TAG_PROBE = re.compile(r":sha256-[0-9a-f]{64}\.(sbom|att|sig|vex)$")


def registry(index, attestations=None, local=False, tags=None):
    """A scripted registry. attestations maps an attestation digest to a manifest dict, raw text, or None (error).
    tags maps a digest-named tag suffix (sbom, att, sig, vex) to its manifest dict; unlisted suffixes are unknown."""
    attestations, tags = attestations or {}, tags or {}

    def imagetools(argv):
        target = argv[-1]
        m = TAG_PROBE.search(target)
        if m:
            return ok(json.dumps(tags[m.group(1)])) if m.group(1) in tags else bad("manifest unknown")
        if "@" in target and target.split("@")[1] in attestations:
            body = attestations[target.split("@")[1]]
            if body is None:
                return bad("manifest unknown")
            return ok(body if isinstance(body, str) else json.dumps(body))
        return ok(json.dumps(index)) if index is not None else bad("no route to host")

    inspect_rule = ((("docker", "image", "inspect"), ok(image_inspect("arm64"))) if local
                    else (("docker", "image", "inspect"), bad("No such image")))
    return FakeRunner([inspect_rule, (("docker", "buildx", "imagetools"), imagetools)])


class Provenance(unittest.TestCase):
    def run_img(self, index, attestations=None, local=False, ref=PINNED, tags=None):
        fake = registry(index, attestations, local, tags)
        return inspect_image(ref, runner=fake), fake

    def test_sbom_published_as_a_digest_named_tag_is_listed(self):
        # Prevents an NVIDIA image, whose SBOM is a sigstore-style tag, reading as "no SBOM published".
        r, fake = self.run_img({"layers": []}, tags={"sbom": {"layers": []}, "sig": {"layers": []}})
        c = by_id(r, "image.sbom")
        self.assertEqual((c["outcome"], c["evidence"]), ("PASS", "declared"))
        self.assertEqual(r["provenance"]["status"], "listed")
        self.assertIs(r["provenance"]["signature_verified"], False)
        self.assertTrue(c["detail"]["signature_tag"].endswith(".sig"))
        self.assertEqual(r["provenance"]["attestations"][0]["subject_digest"], DIGEST)
        self.assertEqual(by_id(r, "image.provenance")["outcome"], "UNKNOWN")
        probes = [c[-1] for c in fake.calls if "--raw" in c and TAG_PROBE.search(c[-1])]
        self.assertEqual(len(probes), 4)
        self.assertFalse(any(c[:2] == ["docker", "pull"] for c in fake.calls))

    def test_attestation_bundle_tag_names_itself_but_stays_unknown(self):
        # Prevents a .att tag, whose predicate type is not read, being promoted to a provenance PASS.
        r, _ = self.run_img({"layers": []}, tags={"att": {"layers": []}})
        c = by_id(r, "image.provenance")
        self.assertEqual(c["outcome"], "UNKNOWN")
        self.assertIn(".att", c["summary"])
        self.assertEqual(r["provenance"]["status"], "listed")
        self.assertEqual(by_id(r, "image.sbom")["outcome"], "UNKNOWN")

    def test_only_a_signature_tag_keeps_status_none_published(self):
        # Prevents a .sig alone counting as an attestation.
        r, _ = self.run_img({"manifests": [plat(ARM, "arm64")]}, tags={"sig": {"layers": []}})
        self.assertEqual(r["provenance"]["status"], "none-published")
        self.assertEqual(by_id(r, "image.sbom")["outcome"], "UNKNOWN")
        self.assertEqual(r["provenance"]["tag_artifacts"], {"sig": f"ubuntu:{DIGEST.replace(':', '-')}.sig"})

    def test_neither_attestation_style_is_unchanged(self):
        # Prevents the tag probe changing the result when there is nothing to find.
        r, _ = self.run_img({"manifests": [plat(ARM, "arm64")]})
        self.assertEqual(r["provenance"]["status"], "none-published")
        self.assertNotIn("tag_artifacts", r["provenance"])
        self.assertTrue(by_id(r, "image.sbom")["summary"].startswith("SBOM attestation not established: the registry lists no"))

    def test_buildkit_attestations_are_not_followed_by_a_tag_probe(self):
        # Prevents four needless registry calls once an attestation manifest was already found.
        _, fake = self.run_img({"manifests": [plat(ARM, "arm64"), att(ATT_ARM, ARM)]}, {ATT_ARM: att_doc(SPDX)})
        self.assertFalse(any(TAG_PROBE.search(c[-1]) for c in fake.calls))

    def test_no_digest_means_no_tag_probe(self):
        # Prevents a probe built from a missing digest.
        _, fake = self.run_img({"layers": []}, local=True, ref="ubuntu:24.04")
        self.assertFalse(any(TAG_PROBE.search(c[-1]) for c in fake.calls))

    def test_sbom_and_provenance_listed(self):
        index = {"manifests": [plat(ARM, "arm64"), att(ATT_ARM, ARM), plat(AMD, "amd64"), att(ATT_AMD, AMD)]}
        r, fake = self.run_img(index, {ATT_ARM: att_doc(SPDX, SLSA)})
        for cid in ("image.sbom", "image.provenance"):
            c = by_id(r, cid)
            self.assertEqual(c["outcome"], "PASS", cid)
            self.assertEqual(c["evidence"], "declared")
            self.assertIn("not verified", c["summary"])
        p = r["provenance"]
        self.assertEqual(p["status"], "listed")
        self.assertIs(p["signature_verified"], False)
        self.assertEqual(p["arm64_manifest_digests"], [ARM])
        self.assertEqual(p["attestations"], [{"attestation_manifest_digest": ATT_ARM, "subject_digest": ARM,
                                              "predicate_types": sorted([SPDX, SLSA])}])
        fetched = [c[-1] for c in fake.calls if c[:4] == ["docker", "buildx", "imagetools", "inspect"]]
        self.assertIn(f"ubuntu@{ATT_ARM}", fetched)
        self.assertNotIn(f"ubuntu@{ATT_AMD}", fetched, "attestations for other platforms are not read")
        self.assertFalse(any(c[:2] == ["docker", "pull"] for c in fake.calls))

    def test_sbom_only_leaves_provenance_unknown(self):
        index = {"manifests": [plat(ARM, "arm64"), att(ATT_ARM, ARM)]}
        r, _ = self.run_img(index, {ATT_ARM: att_doc(SPDX)})
        self.assertEqual(by_id(r, "image.sbom")["outcome"], "PASS")
        self.assertEqual(by_id(r, "image.provenance")["outcome"], "UNKNOWN")

    def test_cyclonedx_counts_as_sbom_and_other_types_do_not(self):
        self.assertEqual(classify_predicate("https://cyclonedx.org/bom"), "sbom")
        self.assertEqual(classify_predicate("https://slsa.dev/provenance/v1"), "provenance")
        self.assertEqual(classify_predicate("https://example.com/vuln-scan"), "other")
        index = {"manifests": [plat(ARM, "arm64"), att(ATT_ARM, ARM)]}
        r, _ = self.run_img(index, {ATT_ARM: att_doc("https://example.com/vuln-scan")})
        self.assertEqual(by_id(r, "image.sbom")["outcome"], "UNKNOWN")
        self.assertEqual(by_id(r, "image.provenance")["outcome"], "UNKNOWN")

    def test_none_published_is_unknown_never_pass(self):
        r, _ = self.run_img({"manifests": [plat(ARM, "arm64")]})
        self.assertEqual(r["provenance"]["status"], "none-published")
        for cid in ("image.sbom", "image.provenance"):
            self.assertEqual(by_id(r, cid)["outcome"], "UNKNOWN")

    def test_attestation_for_another_platform_does_not_count(self):
        index = {"manifests": [plat(ARM, "arm64"), plat(AMD, "amd64"), att(ATT_AMD, AMD)]}
        r, fake = self.run_img(index, {ATT_AMD: att_doc(SPDX, SLSA)})
        self.assertEqual(by_id(r, "image.sbom")["outcome"], "UNKNOWN")
        self.assertEqual(r["provenance"]["status"], "none-published")

    def test_malformed_attestation_manifests_are_unknown_with_errors(self):
        index = {"manifests": [plat(ARM, "arm64"), att(ATT_ARM, ARM)]}
        for body in ("not json {", {"layers": "nope"}, {}, None):
            r, _ = self.run_img(index, {ATT_ARM: body})
            self.assertEqual(by_id(r, "image.sbom")["outcome"], "UNKNOWN", repr(body))
            self.assertEqual(r["provenance"]["status"], "unreadable")
            self.assertTrue(r["provenance"]["errors"])

    def test_malformed_index_entries_do_not_crash(self):
        index = {"manifests": ["junk", None, {"platform": "x"}, plat(ARM, "arm64"),
                               {"digest": ATT_ARM, "annotations": "bad"}]}
        r, _ = self.run_img(index)
        self.assertEqual(by_id(r, "image.sbom")["outcome"], "UNKNOWN")

    def test_malformed_layer_annotations_do_not_crash(self):
        index = {"manifests": [plat(ARM, "arm64"), att(ATT_ARM, ARM)]}
        body = {"layers": ["junk", {"annotations": "bad"}, {"annotations": {"in-toto.io/predicate-type": 5}},
                           {"annotations": {"in-toto.io/predicate-type": SPDX}}]}
        r, _ = self.run_img(index, {ATT_ARM: body})
        self.assertEqual(by_id(r, "image.sbom")["outcome"], "PASS")
        self.assertEqual(r["provenance"]["attestations"][0]["predicate_types"], [SPDX])

    def test_non_sha256_digests_are_ignored_and_never_reach_argv(self):
        evil = "sha256:../../etc/passwd"
        index = {"manifests": [plat(ARM, "arm64"), att(evil, ARM)]}
        r, fake = self.run_img(index, {})
        self.assertEqual(r["provenance"]["status"], "none-published")
        self.assertFalse(any(evil in " ".join(c) for c in fake.calls))

    def test_single_platform_manifest_has_no_attestation_info(self):
        r, _ = self.run_img({"layers": []})
        self.assertEqual(r["provenance"]["status"], "no-manifest-list")
        self.assertEqual(by_id(r, "image.sbom")["outcome"], "UNKNOWN")

    def test_no_arm64_image_means_nothing_to_attest(self):
        r, _ = self.run_img({"manifests": [plat(AMD, "amd64"), att(ATT_AMD, AMD)]})
        self.assertEqual(r["provenance"]["status"], "no-arm64-manifest")
        self.assertEqual(by_id(r, "image.architecture")["outcome"], "FAIL")

    def test_registry_unreachable_is_unknown(self):
        r, _ = self.run_img(None)
        self.assertEqual(by_id(r, "image.sbom")["outcome"], "UNKNOWN")
        self.assertEqual(by_id(r, "image.provenance")["outcome"], "UNKNOWN")

    def test_local_image_still_gets_registry_attestation_metadata(self):
        index = {"manifests": [plat(ARM, "arm64"), att(ATT_ARM, ARM)]}
        r, fake = self.run_img(index, {ATT_ARM: att_doc(SPDX, SLSA)}, local=True)
        self.assertEqual(r["source"], "local image")
        self.assertEqual(by_id(r, "image.sbom")["outcome"], "PASS")
        self.assertFalse(any(c[:2] == ["docker", "pull"] for c in fake.calls))

    def test_local_image_with_unreachable_registry_is_unknown_not_error(self):
        r, _ = self.run_img(None, local=True)
        self.assertEqual(by_id(r, "image.manifest")["outcome"], "PASS")
        self.assertEqual(by_id(r, "image.sbom")["outcome"], "UNKNOWN")

    def test_fetches_are_capped(self):
        digests = ["sha256:" + str(i) * 64 for i in range(5, 11)]
        index = {"manifests": [plat(ARM, "arm64")] + [att(d, ARM) for d in digests]}
        r, fake = self.run_img(index, {d: att_doc(SPDX) for d in digests})
        fetched = [c for c in fake.calls if c[-1].startswith("ubuntu@sha256:") and c[-1] != PINNED]
        self.assertEqual(len(fetched), 4)
        self.assertTrue(any("only the first 4" in e for e in r["provenance"]["errors"]))

    def test_repo_name(self):
        self.assertEqual(repo_name("ubuntu:24.04"), "ubuntu")
        self.assertEqual(repo_name(PINNED), "ubuntu")
        self.assertEqual(repo_name("localhost:5000/team/app:1.2"), "localhost:5000/team/app")
        self.assertEqual(repo_name("localhost:5000/team/app"), "localhost:5000/team/app")
        self.assertEqual(repo_name(f"nvcr.io/nvidia/l4t-base:r36.4.0@{DIGEST}"), "nvcr.io/nvidia/l4t-base")

    def test_tag_reference_uses_repo_digest_for_attestations(self):
        index = {"manifests": [plat(ARM, "arm64"), att(ATT_ARM, ARM)]}
        r, fake = self.run_img(index, {ATT_ARM: att_doc(SPDX)}, ref="myreg:5000/app:1.0")
        self.assertIn(f"myreg:5000/app@{ATT_ARM}", [c[-1] for c in fake.calls])

    def test_invalid_reference_has_no_provenance_and_no_calls(self):
        fake = registry({"manifests": []})
        r = inspect_image("bad ref", runner=fake)
        self.assertEqual(fake.calls, [])
        self.assertNotIn("provenance", r)


if __name__ == "__main__":
    unittest.main()
