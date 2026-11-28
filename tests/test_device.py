import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from egrit_preflight import cli
from egrit_preflight.device import inspect_device
from tests.fakes import FakeRunner, ok


class DeviceTests(unittest.TestCase):
    def read(self, release=None, package=""):
        runner = FakeRunner([(("dpkg-query",), ok(package))])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nv_tegra_release"
            if release is not None:
                path.write_text(release)
            return inspect_device(runner, path)

    def test_reads_independent_sources(self):
        record = self.read("# R36 (release), REVISION: 5.2, BOARD: generic", "install ok installed\t6.2.3-b1")
        self.assertEqual(record["software"], {"jetson_linux": "36.5.2", "jetpack": "6.2.3"})

    def test_partial_install(self):
        record = self.read("# R36 (release), REVISION: 5.2,", "deinstall ok config-files\t6.2.3-b1")
        self.assertEqual(record["software"], {"jetson_linux": "36.5.2", "jetpack": None})

    def test_no_sources(self):
        for release in (None, "# R36 (release), REVISION: 5.invalid,"):
            record = self.read(release)
            with patch.object(cli, "inspect_device", return_value=record):
                out = io.StringIO()
                self.assertEqual(cli.main(["device", "--json", "--strict"], out=out), 3)
                self.assertEqual(json.loads(out.getvalue())["software"], {"jetson_linux": None, "jetpack": None})
