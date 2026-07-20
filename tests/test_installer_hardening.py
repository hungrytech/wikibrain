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
                handler["command"]
                for group in payload["hooks"][event]
                for handler in group.get("hooks", [])
                if "hook --provider claude" in handler.get("command", "")
            ]
            self.assertEqual(len(commands), 1)

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


if __name__ == "__main__":
    unittest.main()
