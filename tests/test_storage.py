from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from wikibrain.models import NormalizedEvent
from wikibrain.storage import BrainStore


class StorageTests(unittest.TestCase):
    def test_connection_context_releases_the_database_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BrainStore(Path(temporary) / "state.db")
            with store.connect() as connection:
                connection.execute("SELECT 1").fetchone()

            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1").fetchone()

    def test_concurrent_wal_writers_do_not_lose_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BrainStore(Path(temporary) / "state.db")

            def write(index: int) -> bool:
                event = NormalizedEvent(
                    provider="codex",
                    name="UserPromptSubmit",
                    session_id="shared-session",
                    turn_id=f"turn-{index}",
                    cwd=temporary,
                )
                inserted, _ = store.capture_prompt(event, f"prompt {index}", 0)
                return inserted

            with ThreadPoolExecutor(max_workers=16) as executor:
                results = list(executor.map(write, range(32)))
            self.assertTrue(all(results))
            counts = store.counts()
            self.assertEqual(counts["events"], 32)
            self.assertEqual(counts["turns"], 32)
            with store.connect() as connection:
                journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(journal_mode.lower(), "wal")

    def test_duplicate_turn_event_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BrainStore(Path(temporary) / "state.db")
            event = NormalizedEvent(
                provider="codex",
                name="UserPromptSubmit",
                session_id="s1",
                turn_id="t1",
                cwd=temporary,
            )
            first, _ = store.capture_prompt(event, "same prompt", 0)
            second, _ = store.capture_prompt(event, "same prompt", 0)
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(store.counts()["events"], 1)
            self.assertEqual(store.counts()["turns"], 1)


if __name__ == "__main__":
    unittest.main()
