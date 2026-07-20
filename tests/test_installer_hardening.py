from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from wikibrain.config import BrainConfig
from wikibrain.installer import (
    EVENTS,
    WINDOWS_HOOK_SHIM_NAME,
    _is_owned_handler,
    _managed_shim_target,
    _windows_shim_content,
    hook_group,
    hook_status,
    install_hooks,
    resolve_brainctl,
)


class InstallerHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = BrainConfig.create(
            self.root / "brain", self.root / "vault", [self.root]
        )
        self.claude = self.root / ".claude" / "settings.json"
        self.codex = self.root / ".codex" / "hooks.json"
        self.paths = {"claude": self.claude, "codex": self.codex}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _fake_brainctl(self) -> Path:
        cellar = self.root / "Cellar" / "wikibrain" / "1.0.0" / "bin"
        cellar.mkdir(parents=True)
        target = cellar / "brainctl"
        target.write_text("#!/bin/sh\nprintf 'brainctl\\n'\n", encoding="utf-8")
        target.chmod(0o755)
        prefix_bin = self.root / "homebrew" / "bin"
        prefix_bin.mkdir(parents=True)
        link = prefix_bin / "brainctl"
        link.symlink_to(target)
        return link

    @unittest.skipIf(os.name == "nt", "POSIX Homebrew shim contract")
    def test_preserves_homebrew_symlink_and_installs_stable_shim(self) -> None:
        brainctl = self._fake_brainctl()

        self.assertEqual(resolve_brainctl(str(brainctl)), str(brainctl))
        install_hooks(
            self.config,
            ["claude", "codex"],
            command=str(brainctl),
            paths=self.paths,
        )

        shim = self.config.home_path / "bin" / "wikibrain-hook"
        self.assertTrue(shim.is_file())
        self.assertTrue(os.access(shim, os.X_OK))
        self.assertIn(str(brainctl), shim.read_text(encoding="utf-8"))
        self.assertNotIn(str(brainctl.resolve()), shim.read_text(encoding="utf-8"))

        for client, path in self.paths.items():
            payload = json.loads(path.read_text(encoding="utf-8"))
            serialized = json.dumps(payload)
            self.assertEqual(serialized.count(f"hook --provider {client}"), 5)
            self.assertIn(str(shim), serialized)
            self.assertNotIn(str(brainctl), serialized)

        statuses = {item["client"]: item for item in hook_status(self.paths)}
        for client in ("claude", "codex"):
            self.assertTrue(statuses[client]["desired"])
            self.assertTrue(statuses[client]["executable"])
            self.assertTrue(statuses[client]["valid"])

    @unittest.skipIf(os.name == "nt", "POSIX PATH shim contract")
    def test_shim_finds_sibling_tools_when_agent_path_omits_homebrew(self) -> None:
        brainctl = self._fake_brainctl()
        wikimap = brainctl.parent / "wikimap"
        wikimap.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        wikimap.chmod(0o755)
        brainctl.resolve().write_text(
            "#!/bin/sh\ncommand -v wikimap\n",
            encoding="utf-8",
        )
        install_hooks(
            self.config,
            ["claude"],
            command=str(brainctl),
            paths=self.paths,
        )
        shim = self.config.home_path / "bin" / "wikibrain-hook"

        completed = subprocess.run(
            [str(shim), "hook", "--provider", "claude"],
            env={"PATH": "/usr/bin:/bin"},
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.strip(), str(wikimap))

    @unittest.skipIf(os.name == "nt", "POSIX shell execution contract")
    def test_missing_brainctl_target_is_fail_open(self) -> None:
        install_hooks(
            self.config,
            ["claude"],
            command=str(self.root / "missing" / "brainctl"),
            paths=self.paths,
        )
        shim = self.config.home_path / "bin" / "wikibrain-hook"

        completed = subprocess.run(
            [str(shim), "hook", "--provider", "claude"],
            input="{}",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "{}\n")
        self.assertEqual(completed.stderr, "")
        status = {
            item["client"]: item for item in hook_status(self.paths)
        }["claude"]
        self.assertFalse(status["executable"])
        self.assertFalse(status["valid"])
        self.assertIn(
            "WikiBrain hook target is missing or not executable",
            status["issues"],
        )

    def test_replaces_stale_owned_handlers_and_preserves_unrelated_hooks(self) -> None:
        stale_groups = {
            event: [
                {
                    "matcher": "stale",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/old/bin/brainctl hook --provider claude",
                            "timeout": 99,
                        },
                        {"type": "command", "command": f"echo keep-{event}"},
                    ],
                },
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/other/bin/brainctl hook --provider claude",
                        }
                    ]
                },
            ]
            for event in EVENTS
        }
        self.claude.parent.mkdir(parents=True)
        self.claude.write_text(
            json.dumps({"theme": "dark", "hooks": stale_groups}),
            encoding="utf-8",
        )

        first = install_hooks(
            self.config,
            ["claude"],
            command=str(self.root / "missing" / "brainctl"),
            paths=self.paths,
        )
        second = install_hooks(
            self.config,
            ["claude"],
            command=str(self.root / "missing" / "brainctl"),
            paths=self.paths,
        )

        self.assertEqual(first[0]["changes"], len(EVENTS))
        self.assertEqual(second[0]["changes"], 0)
        payload = json.loads(self.claude.read_text(encoding="utf-8"))
        self.assertEqual(payload["theme"], "dark")
        serialized = json.dumps(payload)
        self.assertNotIn("/old/bin/brainctl", serialized)
        self.assertNotIn("/other/bin/brainctl", serialized)
        for event in EVENTS:
            self.assertIn(f"echo keep-{event}", serialized)
            commands = [
                handler
                for group in payload["hooks"][event]
                for handler in group.get("hooks", [])
                if _is_owned_handler(handler, "claude")
            ]
            self.assertEqual(len(commands), 1)

    @unittest.skipIf(os.name == "nt", "POSIX executable-bit contract")
    def test_status_reports_non_executable_shim(self) -> None:
        install_hooks(
            self.config,
            ["claude", "codex"],
            command=str(self.root / "missing" / "brainctl"),
            paths=self.paths,
        )
        shim = self.config.home_path / "bin" / "wikibrain-hook"
        shim.chmod(0o600)

        statuses = {item["client"]: item for item in hook_status(self.paths)}

        self.assertFalse(statuses["claude"]["executable"])
        self.assertFalse(statuses["claude"]["valid"])
        self.assertIn(
            "WikiBrain hook shim is missing or not executable",
            statuses["claude"]["issues"],
        )

    def test_invalid_client_does_not_install_shim(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported client"):
            install_hooks(
                self.config,
                ["unknown"],
                command=str(self.root / "missing" / "brainctl"),
                paths=self.paths,
            )

        self.assertFalse(
            (self.config.home_path / "bin" / "wikibrain-hook").exists()
        )

    def test_windows_hook_definitions_use_supported_platform_overrides(self) -> None:
        shim = (
            r"C:\Users\Example User\AppData\Local\WikiBrain\bin"
            rf"\{WINDOWS_HOOK_SHIM_NAME}"
        )

        claude = hook_group(shim, "claude", "SessionStart")["hooks"][0]
        self.assertEqual(claude["command"], "powershell.exe")
        self.assertEqual(
            claude["args"][-4:],
            [shim, "hook", "--provider", "claude"],
        )
        self.assertTrue(_is_owned_handler(claude, "claude"))

        codex = hook_group(shim, "codex", "SessionStart")["hooks"][0]
        self.assertEqual(codex["commandWindows"], codex["command"])
        self.assertIn("-ExecutionPolicy Bypass", codex["commandWindows"])
        self.assertIn(f'-File "{shim}"', codex["commandWindows"])
        self.assertTrue(_is_owned_handler(codex, "codex"))

    def test_windows_shim_preserves_target_and_fails_open(self) -> None:
        target = r"C:\Users\O'Neil\.local\bin\brainctl.exe"
        shim = self.root / WINDOWS_HOOK_SHIM_NAME
        content = _windows_shim_content(target)
        shim.write_text(content, encoding="utf-8")

        self.assertIn("$target = 'C:\\Users\\O''Neil", content)
        self.assertIn("[Console]::Out.WriteLine('{}')", content)
        self.assertIn("exit 0", content)
        self.assertEqual(_managed_shim_target(str(shim)), target)

    @unittest.skipUnless(os.name == "nt", "native Windows contract")
    def test_native_windows_install_writes_valid_powershell_hooks(self) -> None:
        target = self.root / "pipx bin" / "brainctl.exe"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"MZ")

        install_hooks(
            self.config,
            ["claude", "codex"],
            command=str(target),
            paths=self.paths,
        )

        shim = self.config.home_path / "bin" / WINDOWS_HOOK_SHIM_NAME
        self.assertTrue(shim.is_file())
        self.assertEqual(_managed_shim_target(str(shim)), str(target))
        statuses = {item["client"]: item for item in hook_status(self.paths)}
        self.assertTrue(statuses["claude"]["valid"])
        self.assertTrue(statuses["codex"]["valid"])


if __name__ == "__main__":
    unittest.main()
