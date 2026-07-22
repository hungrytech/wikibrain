from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

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

    def test_transaction_preserves_primary_error_when_compensation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BrainStore(Path(temporary) / "state.db")

            def fail_compensation() -> None:
                raise OSError("cleanup failed")

            with self.assertRaisesRegex(ValueError, "primary failure") as raised:
                with store.transaction(on_rollback=fail_compensation):
                    raise ValueError("primary failure")

            notes = getattr(raised.exception, "__notes__", [])
            self.assertTrue(
                any("cleanup failed" in note for note in notes),
                notes,
            )

    def test_transaction_preserves_primary_error_when_close_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BrainStore(Path(temporary) / "state.db")

            class CloseFailingConnection:
                def execute(self, _sql: str) -> None:
                    return None

                def commit(self) -> None:
                    return None

                def rollback(self) -> None:
                    return None

                def close(self) -> None:
                    raise OSError("close failed")

            with patch.object(store, "connect", return_value=CloseFailingConnection()):
                with self.assertRaisesRegex(ValueError, "primary failure") as raised:
                    with store.transaction():
                        raise ValueError("primary failure")

            notes = getattr(raised.exception, "__notes__", [])
            self.assertTrue(any("close failed" in note for note in notes), notes)

    def test_keyboard_interrupt_runs_compensation_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BrainStore(Path(temporary) / "state.db")
            compensation_called = False

            def compensate() -> None:
                nonlocal compensation_called
                compensation_called = True

            with self.assertRaises(KeyboardInterrupt):
                with store.transaction(on_rollback=compensate):
                    raise KeyboardInterrupt()

            self.assertTrue(compensation_called)
            with store.connect() as connection:
                self.assertEqual(connection.execute("SELECT 1").fetchone()[0], 1)

    def test_begin_failure_does_not_run_compensation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BrainStore(Path(temporary) / "state.db")
            lock = store.connect()
            lock.execute("BEGIN IMMEDIATE")
            compensation_called = False

            def compensate() -> None:
                nonlocal compensation_called
                compensation_called = True

            try:
                with self.assertRaises(sqlite3.OperationalError):
                    with store.transaction(on_rollback=compensate):
                        self.fail("transaction body must not run")
            finally:
                lock.rollback()
                lock.close()

            self.assertFalse(compensation_called)

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
