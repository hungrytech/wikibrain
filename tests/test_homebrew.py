from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HomebrewTemplateTests(unittest.TestCase):
    def test_formula_renderer_resolves_release_values_and_is_ruby_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "wikibrain.rb"
            completed = subprocess.run(
                [
                    "python3",
                    str(ROOT / "scripts" / "render_homebrew_formula.py"),
                    "--owner",
                    "example-owner",
                    "--version",
                    "0.1.0",
                    "--source-url",
                    "https://github.com/example-owner/wikibrain/archive/v0.1.0.tar.gz",
                    "--source-sha256",
                    "a" * 64,
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            formula = output.read_text(encoding="utf-8")
            self.assertNotIn("@OWNER@", formula)
            self.assertIn('depends_on "python@3.13"', formula)
            self.assertIn("wikimap-1.1.0.tar.gz", formula)
            self.assertIn("setuptools-83.0.0-py3-none-any.whl", formula)
            self.assertIn(
                'pip_install_and_link resource("wikimap")',
                formula,
            )
            self.assertIn("build_isolation: false", formula)
            self.assertIn('bin}/wikimap --version', formula)
            self.assertIn("brainctl setup", formula)
            syntax = subprocess.run(
                ["ruby", "-c", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(syntax.returncode, 0, syntax.stderr)


if __name__ == "__main__":
    unittest.main()
