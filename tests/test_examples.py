"""The shipped target records: each one loads, cites an NVIDIA page read on a stated date, and is indexed."""

import json
import re
import unittest
from pathlib import Path

from egrit_preflight.image import inspect_image, load_target
from tests.fakes import DIGEST, FakeRunner, image_inspect, ok

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
TARGETS = EXAMPLES / "targets"
RECORDS = sorted(TARGETS.glob("*.json"))
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def by_id(r, cid):
    return next(c for c in r["checks"] if c["id"] == cid)


class TargetLibrary(unittest.TestCase):
    def test_the_library_is_not_empty(self):
        # Prevents every other test here passing vacuously after a move or a glob change.
        self.assertGreaterEqual(len(RECORDS), 3)

    def test_each_record_loads_and_states_what_a_comparison_needs(self):
        # Prevents a record that loads but leaves the four comparisons UNKNOWN for want of a field.
        for path in RECORDS:
            rec, err = load_target(str(path))
            self.assertIsNone(err, path.name)
            self.assertEqual(rec["status"], "declared", path.name)
            self.assertEqual(rec["architecture"], "aarch64", path.name)
            for section, key in (("software", "jetpack"), ("software", "jetson_linux"),
                                 ("runtimes", "cuda"), ("runtimes", "tensorrt")):
                self.assertIsInstance(rec[section][key], str, f"{path.name}: {section}.{key}")
            self.assertEqual(path.name, f"jetpack-{rec['software']['jetpack']}.json")

    def test_each_record_cites_an_nvidia_page_read_on_a_stated_date(self):
        # Prevents an unsourced or undated record, the "not re-checked" state this library replaced.
        for path in sorted(EXAMPLES.rglob("*.json")):
            rec = json.loads(path.read_text(encoding="utf-8"))
            sources = rec.get("sources")
            self.assertTrue(sources, path.name)
            for s in sources:
                self.assertTrue(s["url"].startswith("https://developer.nvidia.com/"), f"{path.name}: {s['url']}")
                self.assertRegex(s["retrieved"], DATE, path.name)
            self.assertNotIn("not re-checked", path.read_text(encoding="utf-8"), path.name)

    def test_each_record_compares_cleanly_against_an_arm64_image(self):
        # Prevents a record the tool refuses (target.record FAIL) or reads as another architecture.
        for path in RECORDS:
            rec = json.loads(path.read_text(encoding="utf-8"))
            major = rec["software"]["jetson_linux"].split(".")[0]
            ref = f"nvcr.io/nvidia/l4t-base:r{major}.4.0@{DIGEST}"
            runner = FakeRunner([(("docker", "image", "inspect"), ok(image_inspect("arm64")))])
            r = inspect_image(ref, str(path), runner=runner)
            ids = {c["id"]: c for c in r["checks"]}
            self.assertNotIn("target.record", ids, path.name)
            self.assertEqual(by_id(r, "target.jetpack")["outcome"], "PASS", path.name)
            self.assertNotEqual(ids.get("target.architecture", {}).get("outcome"), "FAIL", path.name)
            self.assertNotEqual(by_id(r, "target.l4t")["outcome"], "FAIL", path.name)

    def test_the_folder_readme_indexes_every_record_and_only_those(self):
        # Prevents the index drifting from the folder, which the README's own procedure says not to allow.
        index = (TARGETS / "README.md").read_text(encoding="utf-8")
        linked = set(re.findall(r"\]\(([^)/]+\.json)\)", index))
        self.assertEqual(linked, {p.name for p in RECORDS})


if __name__ == "__main__":
    unittest.main()
