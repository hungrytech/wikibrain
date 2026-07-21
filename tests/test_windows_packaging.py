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

    def test_all_readmes_offer_a_safe_ai_assisted_windows_install_prompt(self) -> None:
        prompt = """Install WikiBrain on this Windows machine from https://github.com/hungrytech/wikibrain.
Read the repository's Native Windows instructions first. Before changing anything,
tell me whether native Windows or WSL is the correct path for where my agents and
repositories run. Use the version-pinned installer from the README. Download it,
show me the full PowerShell script, explain the settings changed by initialization,
then stop and wait for my explicit approval before running the script or initializing
WikiBrain. After I approve, install it and finish by running brainctl doctor.
Do not bypass Codex hook trust."""
        fenced_prompt = f"```text\n{prompt}\n```"
        pinned_installer = (
            f"/wikibrain/v{__version__}/scripts/install-windows.ps1"
        )

        for readme_name in (
            "README.md",
            "README.ko.md",
            "README.ja.md",
            "README.zh-CN.md",
        ):
            readme = (ROOT / readme_name).read_text(encoding="utf-8")
            native_start = readme.index('<a id="native-windows"></a>')
            native_end = readme.index("<details>", native_start)
            native_section = readme[native_start:native_end]
            with self.subTest(readme=readme_name):
                self.assertIn(fenced_prompt, native_section)
                self.assertIn(pinned_installer, native_section)
                self.assertLess(
                    native_section.index(fenced_prompt),
                    native_section.index("```powershell"),
                )

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

    def test_getting_started_explains_codex_trust_boundary(self) -> None:
        english = (ROOT / "README.md").read_text(encoding="utf-8")
        korean = (ROOT / "README.ko.md").read_text(encoding="utf-8")

        self.assertIn("## Getting Started", english)
        self.assertIn("## 시작하기", korean)
        for document in (english, korean):
            with self.subTest(document=document[:20]):
                self.assertIn("brainctl remember", document)
                self.assertIn("brainctl recall", document)
                self.assertIn("--clients codex --no-hooks", document)
                self.assertIn("--dangerously-bypass-hook-trust", document)
                self.assertIn("requirements.toml", document)
                self.assertIn("Cobalt-719", document)


if __name__ == "__main__":
    unittest.main()
