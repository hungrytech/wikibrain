from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wikibrain.config import BrainConfig
from wikibrain.installer import (
    EVENTS,
    _is_owned_handler,
    install_hooks,
    uninstall_hooks,
)


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = BrainConfig.create(
            self.root / "brain", self.root / "vault", [self.root]
        )
        self.claude = self.root / ".claude" / "settings.json"
        self.codex = self.root / ".codex" / "hooks.json"
        self.claude.parent.mkdir()
        self.codex.parent.mkdir()
        original = {
            "theme": "dark",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Write",
                        "hooks": [{"type": "command", "command": "echo existing"}],
                    }
                ]
            },
        }
        self.claude.write_text(json.dumps(original), encoding="utf-8")
        self.codex.write_text(json.dumps({"custom": {"keep": True}}), encoding="utf-8")
        self.paths = {"claude": self.claude, "codex": self.codex}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_install_is_idempotent_and_uninstall_preserves_unrelated_data(self) -> None:
        first = install_hooks(
            self.config,
            ["claude", "codex"],
            command="/opt/homebrew/bin/brainctl",
            paths=self.paths,
        )
        second = install_hooks(
            self.config,
            ["claude", "codex"],
            command="/opt/homebrew/bin/brainctl",
            paths=self.paths,
        )
        self.assertEqual([item["changes"] for item in first], [5, 5])
        self.assertEqual([item["changes"] for item in second], [0, 0])
        claude_payload = json.loads(self.claude.read_text(encoding="utf-8"))
        self.assertEqual(claude_payload["theme"], "dark")
        owned = [
            handler
            for event in EVENTS
            for group in claude_payload["hooks"][event]
            for handler in group.get("hooks", [])
            if _is_owned_handler(handler, "claude")
        ]
        self.assertEqual(len(owned), 5)
        self.assertIn("echo existing", json.dumps(claude_payload))

        removed = uninstall_hooks(
            self.config, ["claude", "codex"], paths=self.paths
        )
        self.assertEqual([item["changes"] for item in removed], [5, 5])
        claude_after = json.loads(self.claude.read_text(encoding="utf-8"))
        codex_after = json.loads(self.codex.read_text(encoding="utf-8"))
        self.assertEqual(claude_after["theme"], "dark")
        self.assertIn("echo existing", json.dumps(claude_after))
        self.assertEqual(codex_after["custom"], {"keep": True})

    def test_install_creates_backups(self) -> None:
        install_hooks(
            self.config,
            ["claude"],
            command="/opt/homebrew/bin/brainctl",
            paths=self.paths,
        )
        backups = list(self.claude.parent.glob("settings.json.wikibrain.*.bak"))
        self.assertEqual(len(backups), 1)


if __name__ == "__main__":
    unittest.main()
