"""What a report file can carry to a terminal."""

import unittest

from egrit_preflight.report import dumps


class ReportText(unittest.TestCase):
    def test_report_json_is_ascii_so_cat_cannot_drive_the_terminal(self):
        # Prevents C1 controls and bidi overrides, which JSON does not escape by default, reaching a terminal.
        text = dumps({"image": {"note": "\x9b31m\u202eEVIL\x1b]0;t\x07 caf\u00e9"}})
        self.assertTrue(text.isascii())
        self.assertIn("\\u009b", text)
        self.assertIn("\\u202e", text)


if __name__ == "__main__":
    unittest.main()
