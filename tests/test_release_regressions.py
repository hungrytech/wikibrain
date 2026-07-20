from __future__ import annotations

import json
import tempfile
import threading
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from wikibrain.cli import command_forget, main
from wikibrain.config import BrainConfig
from wikibrain.curation import Curator
from wikibrain.hooks import process_hook
from wikibrain.installer import install_hooks
from wikibrain.models import NormalizedEvent
from wikibrain.storage import BrainStore


ROOT = Path(__file__).resolve().parents[1]
FAKE_WIKIMAP = ROOT / "tests" / "fixtures" / "fake_wikimap.py"


def _config(root: Path) -> tuple[BrainConfig, Path]:
    workspace = root / "workspace"
    workspace.mkdir()
    config = BrainConfig.create(root / "brain", root / "brain" / "vault", [workspace])
    config.wikimap_command = str(FAKE_WIKIMAP)
    config.save()
    return config, workspace


def _prompt(session: str, turn: str, workspace: Path, text: str) -> dict:
    return {
        "session_id": session,
        "turn_id": turn,
        "cwd": str(workspace),
        "hook_event_name": "UserPromptSubmit",
        "prompt": text,
    }


def _stop(session: str, turn: str, workspace: Path, text: str) -> dict:
    return {
        "session_id": session,
        "turn_id": turn,
        "cwd": str(workspace),
        "hook_event_name": "Stop",
        "last_assistant_message": text,
    }


def _forget_args(**values: object) -> Namespace:
    defaults: dict[str, object] = {
        "document": None,
        "session": None,
        "provider": None,
        "reason": "release-regression",
        "cascade": False,
        "apply": True,
        "json": True,
    }
    defaults.update(values)
    return Namespace(**defaults)


class ReleaseRegressionTests(unittest.TestCase):
    def test_deleted_turn_cannot_be_recreated_by_exact_hook_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            prompt_marker = "Deleted prompt marker Orchid-841"
            response_marker = "Deleted response marker Quartz-317"
            prompt = _prompt("replay-turn", "t1", workspace, prompt_marker)
            stop = _stop("replay-turn", "t1", workspace, response_marker)
            process_hook("claude", prompt, config)
            process_hook("claude", stop, config)

            store = BrainStore(config.database_path)
            document = next(
                row
                for row in store.documents_for_session(
                    "replay-turn", "claude"
                )
                if row["kind"] == "session"
            )
            with redirect_stdout(StringIO()):
                command_forget(
                    _forget_args(document=str(document["document_id"])),
                    config.home_path,
                )

            process_hook("claude", prompt, config)
            process_hook("claude", stop, config)
            store.checkpoint()

            self.assertEqual(
                store.documents_for_session("replay-turn", "claude"),
                [],
            )
            with store.connect() as connection:
                self.assertEqual(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM turns
                        WHERE provider = 'claude' AND session_id = 'replay-turn'
                        """
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM events
                        WHERE provider = 'claude' AND session_id = 'replay-turn'
                        """
                    ).fetchone()[0],
                    0,
                )
            persisted = b"".join(
                path.read_bytes()
                for base in (config.home_path, config.vault_path)
                for path in base.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(prompt_marker.encode(), persisted)
            self.assertNotIn(response_marker.encode(), persisted)

    def test_deleted_handoff_cannot_be_recreated_by_compact_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            marker = "Deleted compact marker Topaz-442"
            compact = {
                "session_id": "replay-handoff",
                "cwd": str(workspace),
                "hook_event_name": "PostCompact",
                "compact_summary": marker,
            }
            process_hook("claude", compact, config)
            store = BrainStore(config.database_path)
            document = next(
                row
                for row in store.documents_for_session(
                    "replay-handoff", "claude"
                )
                if row["kind"] == "handoff"
            )
            with redirect_stdout(StringIO()):
                command_forget(
                    _forget_args(document=str(document["document_id"])),
                    config.home_path,
                )

            process_hook("claude", compact, config)
            store.checkpoint()

            self.assertEqual(
                store.documents_for_session("replay-handoff", "claude"),
                [],
            )
            self.assertEqual(store.pending_handoffs(), [])
            persisted = b"".join(
                path.read_bytes()
                for base in (config.home_path, config.vault_path)
                for path in base.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(marker.encode(), persisted)

    def test_handoff_delete_clears_outbox_across_registration_crash_window(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            marker = "Crash-window handoff marker Bronze-527"
            event = NormalizedEvent(
                provider="claude",
                name="PostCompact",
                session_id="handoff-crash-window",
                turn_id=None,
                cwd=str(workspace),
            )
            store = BrainStore(config.database_path)
            captured, handoff = store.capture_handoff(event, marker, 0)
            self.assertTrue(captured)
            self.assertIsNotNone(handoff)
            document_id, document_path = Curator(
                config,
                store,
                type("ImmediateWikimap", (), {"update": lambda self: None})(),
            ).archive_handoff(
                "claude",
                "handoff-crash-window",
                str(workspace),
                marker,
            )
            # Simulate process death before complete_handoff(event_key, id).
            self.assertTrue(document_path.exists())
            self.assertEqual(len(store.pending_handoffs()), 1)

            with redirect_stdout(StringIO()):
                command_forget(
                    _forget_args(document=document_id),
                    config.home_path,
                )
            store.checkpoint()

            self.assertIsNone(store.document(document_id))
            self.assertEqual(store.pending_handoffs(), [])
            with store.connect() as connection:
                self.assertEqual(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM events
                        WHERE session_id = 'handoff-crash-window'
                        """
                    ).fetchone()[0],
                    0,
                )
            persisted = b"".join(
                path.read_bytes()
                for path in config.home_path.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(marker.encode(), persisted)

    def test_session_forget_is_provider_scoped_when_ids_collide(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            for provider, turn in (("claude", "c1"), ("codex", "x1")):
                process_hook(
                    provider,
                    _prompt("shared-id", turn, workspace, f"{provider} marker"),
                    config,
                )
                process_hook(
                    provider,
                    _stop("shared-id", turn, workspace, f"{provider} response"),
                    config,
                )
            store = BrainStore(config.database_path)

            with self.assertRaisesRegex(ValueError, "specify --provider"):
                command_forget(
                    _forget_args(session="shared-id", apply=False),
                    config.home_path,
                )
            with redirect_stdout(StringIO()):
                command_forget(
                    _forget_args(session="shared-id", provider="claude"),
                    config.home_path,
                )

            self.assertEqual(
                store.documents_for_session("shared-id", "claude"),
                [],
            )
            self.assertNotEqual(
                store.documents_for_session("shared-id", "codex"),
                [],
            )
            self.assertTrue(store.session_is_forgotten("claude", "shared-id"))
            self.assertFalse(store.session_is_forgotten("codex", "shared-id"))
            _, result = process_hook(
                "codex",
                _prompt("shared-id", "x2", workspace, "still accepted"),
                config,
            )
            self.assertTrue(result.captured)

    def test_cascade_uses_lineage_from_an_existing_delete_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            process_hook(
                "claude",
                _prompt(
                    "receipt-lineage",
                    "r1",
                    workspace,
                    "기억해줘: 회수할 표식은 Indigo-209야.",
                ),
                config,
            )
            process_hook(
                "claude",
                _stop("receipt-lineage", "r1", workspace, "확인했어."),
                config,
            )
            store = BrainStore(config.database_path)
            memory = next(
                row
                for row in store.documents_for_session(
                    "receipt-lineage", "claude"
                )
                if row["kind"] == "memory"
            )
            memory_id = str(memory["document_id"])

            with redirect_stdout(StringIO()):
                command_forget(
                    _forget_args(document=memory_id),
                    config.home_path,
                )
            self.assertIsNone(store.document(memory_id))
            self.assertNotEqual(
                store.documents_for_session("receipt-lineage", "claude"),
                [],
            )
            with redirect_stdout(StringIO()):
                command_forget(
                    _forget_args(document=memory_id, cascade=True),
                    config.home_path,
                )

            self.assertEqual(
                store.documents_for_session("receipt-lineage", "claude"),
                [],
            )
            self.assertTrue(
                store.session_is_forgotten("claude", "receipt-lineage")
            )

    def test_index_update_cannot_clear_a_newer_dirty_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _ = _config(root)
            store = BrainStore(config.database_path)
            store.mark_index_dirty()
            update_started = threading.Event()
            release_update = threading.Event()

            class BlockingWikimap:
                def update(self) -> None:
                    update_started.set()
                    release_update.wait(timeout=5)

            outcome: list[bool] = []
            worker = threading.Thread(
                target=lambda: outcome.append(
                    Curator(config, store, BlockingWikimap()).update_index()
                )
            )
            worker.start()
            self.assertTrue(update_started.wait(timeout=5))
            store.mark_index_dirty()
            release_update.set()
            worker.join(timeout=5)

            self.assertFalse(worker.is_alive())
            self.assertEqual(outcome, [False])
            self.assertTrue(store.index_dirty())

            class ImmediateWikimap:
                def update(self) -> None:
                    return None

            self.assertTrue(
                Curator(config, store, ImmediateWikimap()).update_index()
            )
            self.assertFalse(store.index_dirty())

    def test_cascade_without_source_lineage_refuses_partial_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)

            class ImmediateWikimap:
                def update(self) -> None:
                    return None

            store = BrainStore(config.database_path)
            memory_id, memory_path = Curator(
                config, store, ImmediateWikimap()
            ).remember(
                "Standalone durable preference.",
                workspace=str(workspace),
                update_index=False,
            )

            with self.assertRaisesRegex(ValueError, "no source session lineage"):
                command_forget(
                    _forget_args(document=memory_id, cascade=True),
                    config.home_path,
                )
            self.assertTrue(memory_path.exists())
            self.assertIsNotNone(store.document(memory_id))

    def test_doctor_is_degraded_before_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "not-initialized"
            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(home),
                        "doctor",
                        "--offline",
                        "--skip-hooks",
                        "--json",
                    ]
                )
            self.assertEqual(code, 1)
            self.assertIn('"initialized": false', output.getvalue())
            self.assertIn('"status": "degraded"', output.getvalue())

    def test_failed_explicit_promotion_is_retried_from_its_own_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            process_hook(
                "claude",
                _prompt(
                    "promotion-retry",
                    "p1",
                    workspace,
                    "기억해줘: 승격 재시도 표식은 Cobalt-719야.",
                ),
                config,
            )
            with patch.object(
                Curator,
                "remember",
                side_effect=OSError("injected promotion failure"),
            ):
                with self.assertRaises(OSError):
                    process_hook(
                        "claude",
                        _stop(
                            "promotion-retry",
                            "p1",
                            workspace,
                            "확인했어.",
                        ),
                        config,
                    )

            store = BrainStore(config.database_path)
            self.assertEqual(len(store.pending_promotions()), 1)
            self.assertEqual(
                store.documents_for_session("promotion-retry", "claude"),
                [],
            )
            self.assertEqual(len(store.pending_completed_turns()), 1)

            process_hook(
                "codex",
                {
                    "session_id": "promotion-recovery",
                    "cwd": str(workspace),
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                },
                config,
            )
            self.assertEqual(store.pending_promotions(), [])
            self.assertEqual(
                {
                    row["kind"]
                    for row in store.documents_for_session(
                        "promotion-retry", "claude"
                    )
                },
                {"session", "memory"},
            )

    def test_same_turn_stop_is_immutable_first_write_wins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            process_hook(
                "codex",
                _prompt("immutable-stop", "i1", workspace, "Prompt."),
                config,
            )
            process_hook(
                "codex",
                _stop("immutable-stop", "i1", workspace, "FIRST-RESPONSE"),
                config,
            )
            _, retry = process_hook(
                "codex",
                _stop("immutable-stop", "i1", workspace, "SECOND-RESPONSE"),
                config,
            )

            store = BrainStore(config.database_path)
            document = next(
                row
                for row in store.documents_for_session(
                    "immutable-stop", "codex"
                )
                if row["kind"] == "session"
            )
            with store.connect() as connection:
                response = connection.execute(
                    """
                    SELECT response FROM turns
                    WHERE provider = 'codex' AND session_id = 'immutable-stop'
                      AND turn_key = 'i1'
                    """
                ).fetchone()[0]
            markdown = Path(document["path"]).read_text(encoding="utf-8")
            self.assertFalse(retry.captured)
            self.assertTrue(retry.duplicate)
            self.assertEqual(response, "FIRST-RESPONSE")
            self.assertIn("FIRST-RESPONSE", markdown)
            self.assertNotIn("SECOND-RESPONSE", markdown)

    def test_explicit_memory_survives_a_session_archive_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            process_hook(
                "claude",
                _prompt(
                    "archive-failure-memory",
                    "a1",
                    workspace,
                    "기억해줘: 독립 승격 표식은 Mint-488이야.",
                ),
                config,
            )
            with patch.object(
                Curator,
                "archive_turn",
                side_effect=OSError("injected session archive failure"),
            ):
                with self.assertRaises(OSError):
                    process_hook(
                        "claude",
                        _stop(
                            "archive-failure-memory",
                            "a1",
                            workspace,
                            "확인했어.",
                        ),
                        config,
                    )

            store = BrainStore(config.database_path)
            self.assertEqual(
                {
                    row["kind"]
                    for row in store.documents_for_session(
                        "archive-failure-memory", "claude"
                    )
                },
                {"memory"},
            )
            self.assertEqual(len(store.pending_completed_turns()), 1)

            process_hook(
                "codex",
                {
                    "session_id": "archive-recovery",
                    "cwd": str(workspace),
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                },
                config,
            )
            self.assertEqual(
                {
                    row["kind"]
                    for row in store.documents_for_session(
                        "archive-failure-memory", "claude"
                    )
                },
                {"memory", "session"},
            )
            self.assertEqual(store.pending_completed_turns(), [])

    def test_claude_stop_waits_for_active_background_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            prompt = {
                "session_id": "background-stop",
                "cwd": str(workspace),
                "hook_event_name": "UserPromptSubmit",
                "prompt": "Wait for the background task.",
            }
            process_hook("claude", prompt, config)
            _, deferred = process_hook(
                "claude",
                {
                    "session_id": "background-stop",
                    "cwd": str(workspace),
                    "hook_event_name": "Stop",
                    "last_assistant_message": "PARTIAL-RESULT",
                    "background_tasks": [
                        {
                            "id": "task-1",
                            "type": "shell",
                            "status": "running",
                        }
                    ],
                    "session_crons": [],
                },
                config,
            )
            store = BrainStore(config.database_path)
            self.assertEqual(deferred.reason, "background-work-pending")
            self.assertEqual(
                store.documents_for_session("background-stop", "claude"),
                [],
            )

            _, completed = process_hook(
                "claude",
                {
                    "session_id": "background-stop",
                    "cwd": str(workspace),
                    "hook_event_name": "Stop",
                    "last_assistant_message": "FINAL-RESULT",
                    "background_tasks": [],
                    "session_crons": [],
                },
                config,
            )
            self.assertTrue(completed.captured)
            document = next(
                row
                for row in store.documents_for_session(
                    "background-stop", "claude"
                )
                if row["kind"] == "session"
            )
            markdown = Path(document["path"]).read_text(encoding="utf-8")
            self.assertIn("FINAL-RESULT", markdown)
            self.assertNotIn("PARTIAL-RESULT", markdown)

    def test_retention_prunes_unarchived_sqlite_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            prompt_marker = "Pending retention marker Umber-308"
            handoff_marker = "Pending compact marker Silver-614"
            process_hook(
                "claude",
                _prompt("pending-retention", "u1", workspace, prompt_marker),
                config,
            )
            store = BrainStore(config.database_path)
            store.capture_handoff(
                NormalizedEvent(
                    provider="claude",
                    name="PostCompact",
                    session_id="pending-handoff-retention",
                    turn_id=None,
                    cwd=str(workspace),
                ),
                handoff_marker,
                0,
            )
            old = (datetime.now(UTC) - timedelta(days=120)).isoformat()
            with store.transaction() as connection:
                connection.execute(
                    """
                    UPDATE turns SET created_at = ?
                    WHERE session_id = 'pending-retention'
                    """,
                    (old,),
                )
                connection.execute(
                    """
                    UPDATE events SET created_at = ?
                    WHERE session_id IN (
                        'pending-retention', 'pending-handoff-retention'
                    )
                    """,
                    (old,),
                )
                connection.execute(
                    """
                    UPDATE handoff_outbox SET created_at = ?
                    WHERE session_id = 'pending-handoff-retention'
                    """,
                    (old,),
                )

            preview = StringIO()
            with redirect_stdout(preview):
                code = main(
                    [
                        "--home",
                        str(config.home_path),
                        "retention",
                        "--days",
                        "90",
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn('"pending_turns": 1', preview.getvalue())
            self.assertIn('"pending_handoffs": 1', preview.getvalue())

            with redirect_stdout(StringIO()):
                code = main(
                    [
                        "--home",
                        str(config.home_path),
                        "retention",
                        "--days",
                        "90",
                        "--apply",
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(store.pending_completed_turns(), [])
            self.assertEqual(store.pending_handoffs(), [])
            store.checkpoint()
            persisted = b"".join(
                path.read_bytes()
                for path in config.home_path.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(prompt_marker.encode(), persisted)
            self.assertNotIn(handoff_marker.encode(), persisted)

    def test_retention_preserves_pending_explicit_memory_promotions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            sessions = {
                "promotion-retention-unarchived": "Saffron-431",
                "promotion-retention-archived": "Jade-862",
            }
            store = BrainStore(config.database_path)
            for session_id, marker in sessions.items():
                prompt_event = NormalizedEvent(
                    provider="claude",
                    name="UserPromptSubmit",
                    session_id=session_id,
                    turn_id="p1",
                    cwd=str(workspace),
                )
                store.capture_prompt(
                    prompt_event,
                    f"기억해줘: 보존할 표식은 {marker}야.",
                    0,
                )
                _, turn = store.capture_stop(
                    NormalizedEvent(
                        provider="claude",
                        name="Stop",
                        session_id=session_id,
                        turn_id="p1",
                        cwd=str(workspace),
                    ),
                    "확인했어.",
                    0,
                )
                self.assertIsNotNone(turn)
                self.assertTrue(
                    store.queue_promotion("claude", session_id, "p1")
                )

            archived_turn = next(
                turn
                for turn in store.pending_completed_turns()
                if turn["session_id"] == "promotion-retention-archived"
            )
            archived_id, _ = Curator(
                config,
                store,
                type("ImmediateWikimap", (), {"update": lambda self: None})(),
            ).archive_turn(archived_turn)
            old = (datetime.now(UTC) - timedelta(days=120)).isoformat()
            with store.transaction() as connection:
                connection.execute(
                    """
                    UPDATE turns SET created_at = ?, completed_at = ?
                    WHERE session_id LIKE 'promotion-retention-%'
                    """,
                    (old, old),
                )
                connection.execute(
                    """
                    UPDATE events SET created_at = ?
                    WHERE session_id LIKE 'promotion-retention-%'
                    """,
                    (old,),
                )
                connection.execute(
                    """
                    UPDATE promotion_outbox SET created_at = ?
                    WHERE session_id LIKE 'promotion-retention-%'
                    """,
                    (old,),
                )
                connection.execute(
                    """
                    UPDATE documents SET created_at = ?
                    WHERE document_id = ?
                    """,
                    (old, archived_id),
                )

            before = datetime.now(UTC).isoformat()
            self.assertEqual(
                store.expired_raw_evidence_counts(before)["pending_turns"],
                0,
            )
            self.assertEqual(store.expired_documents("session", before), [])

            with redirect_stdout(StringIO()):
                code = main(
                    [
                        "--home",
                        str(config.home_path),
                        "retention",
                        "--days",
                        "90",
                        "--apply",
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(len(store.pending_promotions()), 2)
            self.assertIsNotNone(store.document(archived_id))
            with store.connect() as connection:
                self.assertEqual(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM turns
                        WHERE session_id LIKE 'promotion-retention-%'
                        """
                    ).fetchone()[0],
                    2,
                )

            process_hook(
                "codex",
                {
                    "session_id": "promotion-retention-recovery",
                    "cwd": str(workspace),
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                },
                config,
            )
            self.assertEqual(store.pending_promotions(), [])
            for session_id in sessions:
                self.assertIn(
                    "memory",
                    {
                        row["kind"]
                        for row in store.documents_for_session(
                            session_id,
                            "claude",
                        )
                    },
                )

    def test_doctor_uses_the_installed_claude_only_custom_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _ = _config(root)
            fake_brainctl = root / "bin" / "brainctl"
            fake_brainctl.parent.mkdir()
            fake_brainctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_brainctl.chmod(0o755)
            claude_settings = root / "custom" / "claude.json"
            install_hooks(
                config,
                ["claude"],
                command=str(fake_brainctl),
                paths={"claude": claude_settings},
            )

            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(config.home_path),
                        "doctor",
                        "--offline",
                        "--json",
                    ]
                )
            raw_payload = output.getvalue()
            payload = json.loads(raw_payload)
            self.assertEqual(code, 0, raw_payload)
            self.assertEqual(
                {hook["client"] for hook in payload["hooks"]},
                {"claude"},
            )
            self.assertTrue(
                Path(payload["hooks"][0]["path"]).samefile(claude_settings),
            )
            self.assertNotIn("codex_action", raw_payload)


if __name__ == "__main__":
    unittest.main()
