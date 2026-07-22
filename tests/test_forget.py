from __future__ import annotations

import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from wikibrain.cli import command_forget
from wikibrain.config import BrainConfig
from wikibrain.hooks import process_hook
from wikibrain.storage import BrainStore


ROOT = Path(__file__).resolve().parents[1]
FAKE_WIKIMAP = ROOT / "tests" / "fixtures" / "fake_wikimap.py"


class ForgetTests(unittest.TestCase):
    def test_preview_is_non_mutating_and_apply_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            config = BrainConfig.create(root / "brain", root / "vault", [workspace])
            config.wikimap_command = str(FAKE_WIKIMAP)
            config.save()
            prompt = {
                "session_id": "forget-session",
                "turn_id": "forget-turn",
                "cwd": str(workspace),
                "hook_event_name": "UserPromptSubmit",
                "prompt": "The temporary codename is Zephyr-9981.",
            }
            stop = {
                "session_id": "forget-session",
                "turn_id": "forget-turn",
                "cwd": str(workspace),
                "hook_event_name": "Stop",
                "last_assistant_message": "Acknowledged the temporary codename.",
            }
            process_hook("codex", prompt, config)
            process_hook("codex", stop, config)
            store = BrainStore(config.database_path)
            with store.connect() as connection:
                row = connection.execute(
                    "SELECT document_id, path FROM documents WHERE kind = 'session'"
                ).fetchone()
            document_id = row["document_id"]
            path = Path(row["path"])
            preview_args = Namespace(
                document=document_id,
                session=None,
                reason="test",
                apply=False,
                json=True,
            )
            with redirect_stdout(StringIO()):
                command_forget(preview_args, config.home_path)
            self.assertTrue(path.exists())
            self.assertIsNotNone(store.document(document_id))

            apply_args = Namespace(
                document=document_id,
                session=None,
                reason="test",
                apply=True,
                json=True,
            )
            with redirect_stdout(StringIO()):
                command_forget(apply_args, config.home_path)
            self.assertFalse(path.exists())
            self.assertIsNone(store.document(document_id))
            self.assertEqual(store.counts()["turns"], 0)
            self.assertEqual(store.counts()["events"], 0)
            tombstones_after_first_apply = store.counts()["tombstones"]
            self.assertEqual(tombstones_after_first_apply, 1)
            with redirect_stdout(StringIO()):
                command_forget(apply_args, config.home_path)
            self.assertEqual(
                store.counts()["tombstones"],
                tombstones_after_first_apply,
            )


if __name__ == "__main__":
    unittest.main()
