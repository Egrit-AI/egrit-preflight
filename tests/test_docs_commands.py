"""Every `egrit-preflight ...` command shown in a fenced block of the README or docs must parse against the real CLI,
and the docs must not show commands that do not exist."""

import re
import shlex
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from egrit_preflight import cli

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), ROOT / "CONTRIBUTING.md", ROOT / "CHANGELOG.md"]
STOP = {"|", "||", "&&", ";", ">", ">>", "2>&1", "<"}


def fenced_lines(text):
    """Logical lines (continuations joined) inside ``` blocks."""
    lines, inside, current = [], False, ""
    for raw in text.splitlines():
        if raw.strip().startswith("```"):
            inside, current = not inside, ""
            continue
        if not inside:
            continue
        line = raw.rstrip()
        if line.endswith("\\"):
            current += line[:-1] + " "
            continue
        lines.append(current + line)
        current = ""
    return lines


def commands():
    found = []
    for path in DOCS:
        for line in fenced_lines(path.read_text(encoding="utf-8")):
            if not line.strip().startswith("egrit-preflight "):
                continue
            tokens = shlex.split(line, comments=True)
            for i, tok in enumerate(tokens):
                if tok in STOP:
                    tokens = tokens[:i]
                    break
            found.append((path.name, line.strip(), tokens[1:]))
    return found


class DocumentedCommands(unittest.TestCase):
    def test_every_documented_command_parses_against_the_real_cli(self):
        found = commands()
        self.assertGreaterEqual(len(found), 6, "the extractor found almost nothing; it is probably broken")
        for doc, line, argv in found:
            with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
                try:
                    cli.build_parser().parse_args(argv)
                except SystemExit as exit_:
                    self.assertEqual(exit_.code, 0, f"{doc}: `{line}` does not parse")

    def test_every_subcommand_is_documented_at_least_once(self):
        shown = {argv[0] for _, _, argv in commands() if argv}
        self.assertTrue({"doctor", "image", "smoke", "report"} <= shown, shown)

    def test_no_command_is_invented(self):
        for path in DOCS:
            text = path.read_text(encoding="utf-8")
            for line in fenced_lines(text):
                stripped = line.strip()
                self.assertFalse(re.match(r"egrit\s+(?!-)", stripped), f"{path.name}: `{stripped}` is not a command here")
            self.assertNotIn("projects import", text, f"{path.name} names a command that does not exist")
            self.assertNotIn("egrit projects", text, path.name)

    def test_future_features_are_labelled_as_not_available(self):
        text = (ROOT / "docs" / "where-it-fits.md").read_text(encoding="utf-8")
        section = text[text.index("## Optional: Egrit alongside Preflight"):]
        self.assertIn("Not available yet", section)
        self.assertIn("No command for it exists", section)
        self.assertNotIn("```", section, "no runnable example for a feature that does not exist")


if __name__ == "__main__":
    unittest.main()
