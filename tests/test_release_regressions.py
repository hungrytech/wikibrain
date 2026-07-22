from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import tomllib
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from wikibrain import __version__
from wikibrain.cli import (
    _erase_owned_paths,
    _prune_forget_receipts,
    command_forget,
    main,
)
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


def _prompt(session: str, turn: str | None, workspace: Path, text: str) -> dict:
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
    def test_release_version_is_consistent_across_distribution_surfaces(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        version = project["project"]["version"]
        self.assertEqual(__version__, version)

        plugin = json.loads(
            (ROOT / "plugins/wikibrain/.codex-plugin/plugin.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(plugin["version"], version)

        lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
        locked_package = next(
            package
            for package in lock["package"]
            if package["name"] == "wikibrain-agent"
        )
        self.assertEqual(locked_package["version"], version)

        windows_installer = (ROOT / "scripts/install-windows.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(f'[string]$Version = "{version}"', windows_installer)
        self.assertIn(
            f"## [{version}] - ",
            (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
        )
        for readme_name in (
            "README.md",
            "README.ko.md",
            "README.ja.md",
            "README.zh-CN.md",
        ):
            readme = (ROOT / readme_name).read_text(encoding="utf-8")
            self.assertIn(
                f"/v{version}/scripts/install-windows.ps1",
                readme,
                readme_name,
            )

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
            self.assertEqual(store.counts()["tombstones"], 1)

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
            self.assertEqual(store.counts()["handoff_outbox"], 0)
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

    def test_init_reports_codex_manual_and_automatic_readiness_separately(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(root / "brain"),
                        "init",
                        "--clients",
                        "codex",
                        "--no-hooks",
                        "--agents-skill-dir",
                        str(root / "agents-skill"),
                        "--json",
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(code, 0, payload)
            self.assertEqual(
                payload["client_readiness"]["manual_commands"],
                "ready",
            )
            self.assertEqual(
                payload["client_readiness"]["codex_manual_skill"],
                "installed-for-new-session",
            )
            self.assertEqual(
                payload["client_readiness"]["codex_automatic_hooks"],
                "not-installed",
            )
            self.assertIn(
                "does not grant, bypass, or inspect hook trust",
                payload["client_readiness"]["codex_trust_owner"],
            )
            self.assertIn("Manual mode is ready", payload["next"])

            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(root / "automatic-brain"),
                        "init",
                        "--clients",
                        "codex",
                        "--command",
                        sys.executable,
                        "--codex-hooks",
                        str(root / "codex-hooks.json"),
                        "--agents-skill-dir",
                        str(root / "automatic-agents-skill"),
                        "--json",
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(code, 0, payload)
            self.assertEqual(
                payload["client_readiness"]["codex_automatic_hooks"],
                "codex-review-required-unless-already-trusted",
            )
            self.assertIn("open /hooks", payload["next"])

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
                _prompt("pending-retention", None, workspace, prompt_marker),
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
            self.assertEqual(store.counts()["sessions"], 0)
            self.assertEqual(store.counts()["tombstones"], 2)
            self.assertTrue(store.session_is_forgotten("claude", "pending-retention"))
            self.assertTrue(
                store.session_is_forgotten("claude", "pending-handoff-retention")
            )
            captured, _ = store.capture_stop(
                NormalizedEvent(
                    provider="claude",
                    name="Stop",
                    session_id="pending-retention",
                    turn_id=None,
                    cwd=str(workspace),
                ),
                "late replayed response",
                0,
            )
            self.assertFalse(captured)
            self.assertEqual(store.pending_completed_turns(), [])
            store.checkpoint()
            persisted = b"".join(
                path.read_bytes()
                for path in config.home_path.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(prompt_marker.encode(), persisted)
            self.assertNotIn(handoff_marker.encode(), persisted)

    def test_retention_blocks_inflight_turn_archive_after_source_prune(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            session_id = "retention-archive-race"
            store = BrainStore(config.database_path)
            old_event = NormalizedEvent(
                provider="claude",
                name="UserPromptSubmit",
                session_id=session_id,
                turn_id="old-turn",
                cwd=str(workspace),
            )
            captured, _ = store.capture_prompt(old_event, "expired secret", 0)
            self.assertTrue(captured)
            captured, _ = store.capture_stop(
                NormalizedEvent(
                    provider="claude",
                    name="Stop",
                    session_id=session_id,
                    turn_id="old-turn",
                    cwd=str(workspace),
                ),
                "expired response",
                0,
            )
            self.assertTrue(captured)
            stale_turn = next(
                row
                for row in store.pending_completed_turns()
                if row["turn_key"] == "old-turn"
            )
            captured, _ = store.capture_prompt(
                NormalizedEvent(
                    provider="claude",
                    name="UserPromptSubmit",
                    session_id=session_id,
                    turn_id="new-turn",
                    cwd=str(workspace),
                ),
                "live prompt",
                0,
            )
            self.assertTrue(captured)
            old = (datetime.now(UTC) - timedelta(days=120)).isoformat()
            cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat()
            with store.transaction() as connection:
                connection.execute(
                    """
                    UPDATE turns SET created_at = ?, completed_at = ?
                    WHERE provider = 'claude' AND session_id = ?
                      AND turn_key = 'old-turn'
                    """,
                    (old, old, session_id),
                )
                connection.execute(
                    """
                    UPDATE events SET created_at = ?
                    WHERE provider = 'claude' AND session_id = ?
                      AND turn_key = 'old-turn'
                    """,
                    (old, session_id),
                )

            store.prune_expired_raw_evidence(cutoff)
            self.assertFalse(store.session_is_forgotten("claude", session_id))
            document_id, path = Curator(
                config,
                store,
                cast(
                    Any,
                    type("ImmediateWikimap", (), {"update": lambda self: None})(),
                ),
            ).archive_turn(stale_turn)
            self.assertFalse(path.exists())
            self.assertIsNone(store.document(document_id))
            with store.connect() as connection:
                live = connection.execute(
                    """
                    SELECT response FROM turns
                    WHERE provider = 'claude' AND session_id = ?
                      AND turn_key = 'new-turn'
                    """,
                    (session_id,),
                ).fetchone()
            self.assertIsNotNone(live)
            self.assertIsNone(live["response"])

    def test_retention_blocks_inflight_handoff_archive_after_source_prune(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            store = BrainStore(config.database_path)
            session_id = "retention-handoff-race"
            summary = "expired handoff secret"
            captured, stale_handoff = store.capture_handoff(
                NormalizedEvent(
                    provider="claude",
                    name="PostCompact",
                    session_id=session_id,
                    turn_id=None,
                    cwd=str(workspace),
                ),
                summary,
                0,
            )
            self.assertTrue(captured)
            self.assertIsNotNone(stale_handoff)
            assert stale_handoff is not None
            event_key = str(stale_handoff["event_key"])
            captured, _ = store.capture_prompt(
                NormalizedEvent(
                    provider="claude",
                    name="UserPromptSubmit",
                    session_id=session_id,
                    turn_id="new-turn",
                    cwd=str(workspace),
                ),
                "live prompt",
                0,
            )
            self.assertTrue(captured)
            old = (datetime.now(UTC) - timedelta(days=120)).isoformat()
            cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat()
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE events SET created_at = ? WHERE event_key = ?",
                    (old, event_key),
                )
                connection.execute(
                    "UPDATE handoff_outbox SET created_at = ? WHERE event_key = ?",
                    (old, event_key),
                )

            store.prune_expired_raw_evidence(cutoff)
            self.assertFalse(store.session_is_forgotten("claude", session_id))
            document_id, path = Curator(
                config,
                store,
                cast(
                    Any,
                    type("ImmediateWikimap", (), {"update": lambda self: None})(),
                ),
            ).archive_handoff(
                "claude",
                session_id,
                str(workspace),
                summary,
                event_key=str(event_key),
                captured_at=str(stale_handoff["created_at"]),
            )
            self.assertFalse(path.exists())
            self.assertIsNone(store.document(document_id))

    def test_retention_compacts_orphan_source_tombstones_without_other_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _ = _config(root)
            store = BrainStore(config.database_path)
            with store.transaction() as connection:
                store._insert_tombstone(
                    connection,
                    "source-turn:claude:orphan-session:t1",
                    "legacy-retention",
                    {
                        "provider": "claude",
                        "session_id": "orphan-session",
                        "turn_key": "t1",
                    },
                )
                store._insert_tombstone(
                    connection,
                    "source-prompt:claude:orphan-session:prompt-hash",
                    "legacy-retention",
                    {
                        "provider": "claude",
                        "session_id": "orphan-session",
                        "turn_key": "t1",
                    },
                )

            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(config.home_path),
                        "retention",
                        "--apply",
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn('"compacted_sessions": 1', output.getvalue())
            self.assertEqual(store.counts()["tombstones"], 1)
            self.assertTrue(
                store.session_is_forgotten("claude", "orphan-session")
            )

    def test_retention_bounds_failed_explicit_memory_promotions(self) -> None:
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
                    UPDATE documents
                    SET created_at = ?,
                        metadata_json = json_set(
                            metadata_json, '$.captured_at', ?
                        )
                    WHERE document_id = ?
                    """,
                    (old, old, archived_id),
                )

            before = (datetime.now(UTC) - timedelta(days=90)).isoformat()
            self.assertEqual(
                store.expired_raw_evidence_counts(before)["pending_turns"],
                1,
            )
            self.assertEqual(
                [str(row["document_id"]) for row in store.expired_documents("session", before)],
                [archived_id],
            )
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE documents SET metadata_json = ? WHERE document_id = ?",
                    ("{malformed", archived_id),
                )
            self.assertEqual(
                [str(row["document_id"]) for row in store.expired_documents("session", before)],
                [archived_id],
            )

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
            self.assertEqual(store.pending_promotions(), [])
            self.assertIsNone(store.document(archived_id))
            with store.connect() as connection:
                self.assertEqual(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM turns
                        WHERE session_id LIKE 'promotion-retention-%'
                        """
                    ).fetchone()[0],
                    0,
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
                self.assertEqual(
                    store.documents_for_session(session_id, "claude"),
                    [],
                )

    def test_schema_v8_compacts_legacy_lifecycle_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            store = BrainStore(config.database_path)
            event = NormalizedEvent(
                provider="claude",
                name="PostCompact",
                session_id="legacy-handoff",
                turn_id=None,
                cwd=str(workspace),
            )
            captured, handoff = store.capture_handoff(event, "legacy summary", 0)
            self.assertTrue(captured)
            assert handoff is not None
            document_id, _ = Curator(
                config,
                store,
                cast(Any, type("ImmediateWikimap", (), {"update": lambda self: None})()),
            ).archive_handoff("claude", "legacy-handoff", str(workspace), "legacy summary")
            source_document = "legacy-document"
            base_receipt = {
                "source_document": source_document,
                "provider": "claude",
                "session_id": "legacy-turn",
                "turn_key": "t1",
            }
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE handoff_outbox SET document_id = ? WHERE event_key = ?",
                    (document_id, str(handoff["event_key"])),
                )
                store._insert_tombstone(
                    connection,
                    f"document:{source_document}",
                    "test",
                    {"provider": "claude", "session_id": "legacy-turn"},
                )
                for selector in (
                    "source-turn:claude:legacy-turn:t1",
                    "source-prompt:claude:legacy-turn:prompt-hash",
                    "source-response:claude:legacy-turn:response-hash",
                ):
                    store._insert_tombstone(
                        connection, selector, "test", dict(base_receipt)
                    )
                connection.execute(
                    """
                    INSERT INTO tombstones(
                        tombstone_id, selector, reason, created_at, receipt_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "malformed-legacy",
                        "source-event:malformed-legacy",
                        "test",
                        datetime.now(UTC).isoformat(),
                        "{not-json",
                    ),
                )
                connection.execute(
                    "UPDATE metadata SET value = '6' WHERE key = 'schema_version'"
                )

            migrated = BrainStore(config.database_path)
            self.assertEqual(migrated.counts()["handoff_outbox"], 0)
            self.assertEqual(migrated.counts()["tombstones"], 2)
            handoff_document = migrated.document(document_id)
            assert handoff_document is not None
            metadata = json.loads(str(handoff_document["metadata_json"]))
            self.assertEqual(metadata["source_event_key"], str(handoff["event_key"]))
            receipt = migrated.tombstone_receipt(f"document:{source_document}")
            assert receipt is not None
            self.assertEqual(receipt["prompt_hash"], "prompt-hash")
            self.assertEqual(receipt["response_hash"], "response-hash")

    def test_no_turn_id_prompt_remains_idempotent_while_original_is_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            store = BrainStore(config.database_path)
            event = NormalizedEvent(
                provider="claude",
                name="UserPromptSubmit",
                session_id="long-pending-dedupe",
                turn_id=None,
                cwd=str(workspace),
            )
            captured, turn_key = store.capture_prompt(event, "same pending prompt", 0)
            self.assertTrue(captured)
            old = (datetime.now(UTC) - timedelta(days=1)).isoformat()
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE turns SET created_at = ? WHERE turn_key = ?",
                    (old, turn_key),
                )

            duplicate, duplicate_key = store.capture_prompt(
                event, "same pending prompt", 0
            )

            self.assertFalse(duplicate)
            self.assertEqual(duplicate_key, turn_key)
            self.assertEqual(store.counts()["turns"], 1)

    def test_owned_file_erasure_prunes_empty_calendar_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _ = _config(root)
            path = (
                config.vault_path
                / "sessions"
                / "2020"
                / "01"
                / "02"
                / "turn.md"
            )
            path.parent.mkdir(parents=True)
            path.write_text("old", encoding="utf-8")

            _erase_owned_paths(config, [str(path)])

            self.assertFalse(path.exists())
            self.assertFalse((config.vault_path / "sessions").exists())

    def test_forget_receipts_keep_only_the_newest_hundred(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipts = Path(temporary)
            for index in range(105):
                path = receipts / f"forget-{index:03d}.json"
                path.write_text("{}\n", encoding="utf-8")
                os.utime(path, (index, index))

            _prune_forget_receipts(receipts)

            remaining = sorted(receipts.glob("forget-*.json"))
            self.assertEqual(len(remaining), 100)
            self.assertEqual(remaining[0].name, "forget-005.json")

    def test_retention_uses_conversation_time_and_does_not_protect_stale_promotions_forever(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace = _config(root)
            store = BrainStore(config.database_path)
            old = (datetime.now(UTC) - timedelta(days=120)).isoformat()
            cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat()

            for session_id in ("late-archive", "never-archived"):
                prompt_event = NormalizedEvent(
                    provider="claude",
                    name="UserPromptSubmit",
                    session_id=session_id,
                    turn_id="p1",
                    cwd=str(workspace),
                )
                store.capture_prompt(prompt_event, f"remember {session_id}", 0)
                _, turn = store.capture_stop(
                    NormalizedEvent(
                        provider="claude",
                        name="Stop",
                        session_id=session_id,
                        turn_id="p1",
                        cwd=str(workspace),
                    ),
                    "done",
                    0,
                )
                self.assertIsNotNone(turn)
                self.assertTrue(store.queue_promotion("claude", session_id, "p1"))
                with store.transaction() as connection:
                    connection.execute(
                        """
                        UPDATE turns SET created_at = ?, completed_at = ?
                        WHERE provider = 'claude' AND session_id = ? AND turn_key = 'p1'
                        """,
                        (old, old, session_id),
                    )
                    connection.execute(
                        """
                        UPDATE promotion_outbox SET created_at = ?
                        WHERE provider = 'claude' AND session_id = ? AND turn_key = 'p1'
                        """,
                        (old, session_id),
                    )

            late_turn = next(
                turn
                for turn in store.pending_completed_turns()
                if turn["session_id"] == "late-archive"
            )
            late_document_id, _ = Curator(
                config,
                store,
                type("ImmediateWikimap", (), {"update": lambda self: None})(),
            ).archive_turn(late_turn)

            expired = store.expired_documents("session", cutoff)
            self.assertEqual(
                [str(row["document_id"]) for row in expired],
                [late_document_id],
            )
            self.assertEqual(
                store.expired_raw_evidence_counts(cutoff)["pending_turns"],
                1,
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
