from __future__ import annotations

import re
import unittest
from pathlib import Path

from wikibrain import __version__
from wikibrain.installer import EVENTS


ROOT = Path(__file__).resolve().parents[1]


class WindowsPackagingTests(unittest.TestCase):
    def test_installer_and_readmes_use_the_release_version(self) -> None:
        installer = (ROOT / "scripts" / "install-windows.ps1").read_text(
            encoding="utf-8"
        )
        english = (ROOT / "README.md").read_text(encoding="utf-8")
        korean = (ROOT / "README.ko.md").read_text(encoding="utf-8")

        self.assertIn(f'[string]$Version = "{__version__}"', installer)
        expected_path = (
            f"/wikibrain/v{__version__}/scripts/install-windows.ps1"
        )
        self.assertIn(expected_path, english)
        self.assertIn(expected_path, korean)

    def test_windows_installer_is_review_first_and_does_not_use_iex(self) -> None:
        installer = (ROOT / "scripts" / "install-windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("[switch]$Initialize", installer)
        self.assertIn("Get-Command \"winget.exe\"", installer)
        self.assertIn('"pipx", "install", "--force"', installer)
        self.assertNotRegex(
            installer,
            re.compile(r"\b(?:iex|Invoke-Expression)\b", re.IGNORECASE),
        )

    def test_language_links_and_hook_tables_are_complete(self) -> None:
        english = (ROOT / "README.md").read_text(encoding="utf-8")
        korean = (ROOT / "README.ko.md").read_text(encoding="utf-8")

        self.assertIn('href="README.ko.md"', english)
        self.assertIn('href="README.md"', korean)
        for event in EVENTS:
            with self.subTest(event=event):
                self.assertIn(f"`{event}`", english)
                self.assertIn(f"`{event}`", korean)


if __name__ == "__main__":
    unittest.main()
