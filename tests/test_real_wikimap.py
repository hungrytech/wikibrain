from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from wikibrain.config import BrainConfig, atomic_write_text
from wikibrain.hooks import process_hook
from wikibrain.wikimap_adapter import WikimapAdapter


REAL_WIKIMAP = os.environ.get("WIKIMAP_BIN")


@unittest.skipUnless(REAL_WIKIMAP, "set WIKIMAP_BIN for the real CLI contract")
class RealWikimapContractTests(unittest.TestCase):
    def test_update_search_doctor_and_cross_agent_recall(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            config = BrainConfig.create(root / "brain", root / "vault", [workspace])
            config.wikimap_command = str(REAL_WIKIMAP)
            config.save()
            adapter = WikimapAdapter(config.vault_path, str(REAL_WIKIMAP))

            atomic_write_text(
                config.vault_path / "seed.md",
                "# Seed\n\nThe real contract marker is Quasar-2804.\n",
            )
            self.assertIn("indexed", adapter.update())
            hits = adapter.search("Quasar-2804")
            self.assertTrue(hits)
            self.assertIn("Quasar-2804", hits[0].snippet)
            self.assertTrue(adapter.doctor()["healthy"])

            process_hook(
                "claude",
                {
                    "session_id": "real-claude",
                    "cwd": str(workspace),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "The cross-agent marker is Pulsar-6107.",
                },
                config,
            )
            process_hook(
                "claude",
                {
                    "session_id": "real-claude",
                    "cwd": str(workspace),
                    "hook_event_name": "Stop",
                    "last_assistant_message": "Confirmed marker Pulsar-6107.",
                },
                config,
            )
            output, result = process_hook(
                "codex",
                {
                    "session_id": "real-codex",
                    "cwd": str(workspace),
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                },
                config,
            )
            self.assertIn("Pulsar-6107", result.context)
            self.assertEqual(
                output["hookSpecificOutput"]["hookEventName"], "SessionStart"
            )


if __name__ == "__main__":
    unittest.main()
