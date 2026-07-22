from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from threading import Barrier, Lock
from unittest.mock import patch

from wikibrain.config import BrainConfig
from wikibrain.cli import command_forget
from wikibrain.curation import Curator
from wikibrain.hooks import process_hook
from wikibrain.recall import RecallService
from wikibrain.storage import BrainStore, adaptive_memory_id
from wikibrain.wikimap_adapter import WikimapAdapter


ROOT = Path(__file__).resolve().parents[1]
FAKE_WIKIMAP = ROOT / "tests" / "fixtures" / "fake_wikimap.py"


class AdaptiveMemoryTests(unittest.TestCase):
    def make_brain(
        self, root: Path
    ) -> tuple[BrainConfig, Path, BrainStore, Curator, RecallService]:
        workspace = root / "project"
        workspace.mkdir()
        config = BrainConfig.create(root / "brain", root / "brain" / "vault", [workspace])
        config.wikimap_command = str(FAKE_WIKIMAP)
        config.adaptive_memory_enabled = True
        config.adaptive_memory_window_days = 60
        config.adaptive_memory_min_sessions = 3
        config.adaptive_memory_min_days = 3
        config.adaptive_memory_min_injections = 2
        config.adaptive_memory_max_chars = 2_000
        config.save()
        store = BrainStore(config.database_path)
        wikimap = WikimapAdapter(config.vault_path, config.wikimap_command)
        curator = Curator(config, store, wikimap)
        recall = RecallService(config, store, wikimap)
        return config, workspace, store, curator, recall

    @staticmethod
    def register_source(
        config: BrainConfig,
        workspace: Path,
        store: BrainStore,
        *,
        document_id: str = "turn-source",
    ) -> Path:
        path = config.vault_path / "sessions" / f"{document_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            f'id: "{document_id}"\n'
            'type: "session"\n'
            f'workspace: "{workspace}"\n'
            'captured_at: "2026-01-01T00:00:00+00:00"\n'
            "---\n\n"
            "# Conversation handoff\n\n"
            "Project Atlas uses port 6432 and uv for locked commands.\n",
            encoding="utf-8",
        )
        self_registered = store.register_document(
            document_id,
            "session",
            path,
            provider="claude",
            session_id="source-session",
            turn_key="source-turn",
            workspace=str(workspace.resolve()),
            metadata={"captured_at": "2026-01-01T00:00:00+00:00"},
        )
        if not self_registered:
            raise AssertionError("source registration failed")
        return path

    def test_usage_requires_distinct_sessions_and_days_and_deduplicates_replays(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace, store, _, _ = self.make_brain(root)
            self.register_source(config, workspace, store)
            base = datetime(2026, 6, 1, tzinfo=UTC)
            store.record_document_usage(
                "turn-source",
                consumer_provider="codex",
                consumer_session_id="expired-session",
                searched=True,
                injected=True,
                used_at=(base - timedelta(days=61)).isoformat(),
                window_days=60,
                min_sessions=3,
                min_days=3,
                min_injections=2,
            )

            first = store.record_document_usage(
                "turn-source",
                consumer_provider="claude",
                consumer_session_id="consumer-1",
                searched=True,
                injected=True,
                used_at=base.isoformat(),
                window_days=60,
                min_sessions=3,
                min_days=3,
                min_injections=2,
            )
            replay = store.record_document_usage(
                "turn-source",
                consumer_provider="claude",
                consumer_session_id="consumer-1",
                searched=True,
                injected=True,
                used_at=(base + timedelta(hours=2)).isoformat(),
                window_days=60,
                min_sessions=3,
                min_days=3,
                min_injections=2,
            )
            second = store.record_document_usage(
                "turn-source",
                consumer_provider="codex",
                consumer_session_id="consumer-2",
                searched=True,
                injected=True,
                used_at=(base + timedelta(days=1)).isoformat(),
                window_days=60,
                min_sessions=3,
                min_days=3,
                min_injections=2,
            )
            third = store.record_document_usage(
                "turn-source",
                consumer_provider="claude",
                consumer_session_id="consumer-3",
                searched=False,
                injected=True,
                used_at=(base + timedelta(days=2)).isoformat(),
                window_days=60,
                min_sessions=3,
                min_days=3,
                min_injections=2,
            )

            self.assertFalse(first["eligible"])
            self.assertEqual(replay["distinct_sessions"], 1)
            self.assertEqual(second["distinct_days"], 2)
            self.assertTrue(third["eligible"])
            self.assertEqual(third["distinct_sessions"], 3)
            self.assertEqual(third["distinct_days"], 3)
            self.assertEqual(third["context_injections"], 3)
            with store.connect() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM document_usage").fetchone()[0],
                    3,
                )

    def test_recall_promotes_only_injected_raw_evidence_and_not_memory_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace, store, _, recall = self.make_brain(root)
            source_path = self.register_source(config, workspace, store)
            config.adaptive_memory_min_sessions = 1
            config.adaptive_memory_min_days = 1
            config.adaptive_memory_min_injections = 1

            context = recall.context(
                str(workspace),
                "Atlas port 6432",
                consumer_provider="claude",
                consumer_session_id="consumer-1",
            )

            self.assertIn("Project Atlas uses port 6432", context)
            memory_id = adaptive_memory_id("turn-source")
            memory = store.document(memory_id)
            self.assertIsNotNone(memory)
            assert memory is not None
            self.assertEqual(memory["kind"], "memory")
            metadata = json.loads(str(memory["metadata_json"]))
            self.assertEqual(metadata["memory_kind"], "adaptive")
            self.assertEqual(metadata["adaptive_source_document_id"], "turn-source")
            memory_path = Path(str(memory["path"]))
            self.assertTrue(memory_path.is_file())
            self.assertIn("Project Atlas uses port 6432", memory_path.read_text(encoding="utf-8"))
            self.assertLessEqual(len(memory_path.read_text(encoding="utf-8")), 4_000)

            recall.context(
                str(workspace),
                "Atlas port 6432",
                consumer_provider="codex",
                consumer_session_id="consumer-2",
            )
            with store.connect() as connection:
                usage_ids = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT DISTINCT document_id FROM document_usage"
                    ).fetchall()
                }
            self.assertEqual(usage_ids, {"turn-source"})
            self.assertTrue(source_path.is_file())

    def test_retention_preserves_adaptive_memory_but_explicit_forget_cascades(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace, store, curator, _ = self.make_brain(root)
            source_path = self.register_source(config, workspace, store)
            usage = {
                "distinct_sessions": 3,
                "distinct_days": 3,
                "search_sessions": 3,
                "context_injections": 3,
                "last_used_at": "2026-06-03T00:00:00+00:00",
            }
            memory_id, memory_path = curator.promote_adaptive(
                "turn-source",
                "Project Atlas uses port 6432.",
                usage,
            )

            retention_receipt = store.forget_document(
                "turn-source", "retention", preserve_adaptive=True
            )
            self.assertEqual(retention_receipt["paths"], [str(source_path.resolve())])
            self.assertIsNotNone(store.document(memory_id))
            self.assertTrue(memory_path.is_file())

            source_path.unlink()
            output = StringIO()
            with redirect_stdout(output):
                command_forget(
                    Namespace(
                        document="turn-source",
                        session=None,
                        provider=None,
                        cascade=False,
                        reason="retention",
                        apply=True,
                        json=True,
                    ),
                    config.home_path,
                )
            # A caller-controlled reason must not impersonate internal retention.
            forget_receipt = json.loads(output.getvalue())
            self.assertIn(str(memory_path.resolve()), forget_receipt["paths"])
            self.assertIn(memory_id, forget_receipt["derived_adaptive_memories"])
            self.assertIsNone(store.document(memory_id))
            self.assertFalse(memory_path.exists())

    def test_manual_recall_without_consumer_identity_does_not_count_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config, workspace, store, _, recall = self.make_brain(Path(temporary))
            config.adaptive_memory_min_sessions = 1
            config.adaptive_memory_min_days = 1
            config.adaptive_memory_min_injections = 1
            self.register_source(config, workspace, store)

            context = recall.context(str(workspace), "Project")

            self.assertIn("turn-source", context)
            self.assertIsNone(store.document(adaptive_memory_id("turn-source")))
            with store.connect() as connection:
                usage_count = connection.execute(
                    "SELECT COUNT(*) FROM document_usage"
                ).fetchone()[0]
            self.assertEqual(usage_count, 0)

    def test_hook_fallback_session_does_not_count_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config, workspace, store, _, _ = self.make_brain(Path(temporary))
            self.register_source(config, workspace, store)

            process_hook(
                "claude",
                {
                    "hook_event_name": "UserPromptSubmit",
                    "cwd": str(workspace),
                    "prompt": "Project",
                },
                config,
            )

            with store.connect() as connection:
                usage = connection.execute(
                    "SELECT consumer_provider, consumer_session_id "
                    "FROM document_usage WHERE document_id = ?",
                    ("turn-source",),
                ).fetchall()
            self.assertEqual(usage, [])

    def test_concurrent_promotions_share_one_deterministic_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config, workspace, store, curator, _ = self.make_brain(Path(temporary))
            self.register_source(config, workspace, store)
            memory_id = adaptive_memory_id("turn-source")
            barrier = Barrier(2)
            gate = Lock()
            initial_checks = 0
            original_document = store.document

            def synchronized_document(document_id: str):
                nonlocal initial_checks
                if document_id == memory_id:
                    with gate:
                        initial_checks += 1
                        should_wait = initial_checks <= 2
                    if should_wait:
                        barrier.wait(timeout=5)
                return original_document(document_id)

            usage = {
                "distinct_sessions": 3,
                "distinct_days": 3,
                "search_sessions": 3,
                "context_injections": 3,
                "last_used_at": "2026-06-03T00:00:00+00:00",
            }
            with patch.object(store, "document", side_effect=synchronized_document):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(
                        executor.map(
                            lambda evidence: curator.promote_adaptive(
                                "turn-source", evidence, usage
                            ),
                            ["Alpha evidence", "Beta evidence"],
                        )
                    )

            paths = {result[1] for result in results if result is not None}
            self.assertEqual(len(paths), 1)
            only_path = next(iter(paths))
            self.assertEqual(
                only_path.parent, config.vault_path / "memories" / "adaptive"
            )
            memory_files = list((config.vault_path / "memories").rglob("*.md"))
            self.assertEqual(memory_files, [only_path])
            registered = store.document(memory_id)
            self.assertIsNotNone(registered)
            assert registered is not None
            self.assertEqual(Path(str(registered["path"])), next(iter(paths)))

    def test_stale_promotion_cannot_recreate_memory_after_source_forget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace, store, curator, _ = self.make_brain(root)
            self.register_source(config, workspace, store)
            source = store.document("turn-source")
            assert source is not None
            store.forget_document("turn-source", "user-request")

            promoted = curator.promote_adaptive(
                "turn-source",
                "Project Atlas uses port 6432.",
                {
                    "distinct_sessions": 3,
                    "distinct_days": 3,
                    "search_sessions": 3,
                    "context_injections": 3,
                    "last_used_at": "2026-06-03T00:00:00+00:00",
                },
                source_snapshot=dict(source),
            )

            self.assertIsNone(promoted)
            self.assertIsNone(store.document(adaptive_memory_id("turn-source")))
            self.assertFalse(any((config.vault_path / "memories").rglob("*.md")))

    def test_superseding_source_blocks_and_hides_adaptive_derivatives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config, workspace, store, curator, recall = self.make_brain(Path(temporary))
            self.register_source(config, workspace, store)
            usage = store.record_document_usage(
                "turn-source", consumer_provider="codex",
                consumer_session_id="consumer-1", searched=True, injected=True,
                min_sessions=1, min_days=1, min_injections=1,
            )
            self.assertIsNotNone(
                curator.promote_adaptive("turn-source", "Project state: green", usage)
            )
            adaptive_id = adaptive_memory_id("turn-source")
            curator.remember(
                "Project state: blue", workspace=str(workspace.resolve()),
                supersedes=["turn-source"], update_index=False,
            )
            self.assertTrue(store.document_is_superseded(adaptive_id))
            self.assertNotIn("Project state: green", recall.context(str(workspace), "Project"))

            root = Path(temporary) / "second"
            root.mkdir()
            config2, workspace2, store2, curator2, _ = self.make_brain(root)
            self.register_source(config2, workspace2, store2)
            source_row = store2.document("turn-source")
            if source_row is None:
                self.fail("source fixture was not registered")
            snapshot = dict(source_row)
            curator2.remember(
                "Replacement", workspace=str(workspace2.resolve()),
                supersedes=["turn-source"], update_index=False,
            )
            stale_usage = {
                "eligible": True, "distinct_sessions": 3, "distinct_days": 3,
                "search_sessions": 3, "context_injections": 3,
            }
            self.assertIsNone(
                curator2.promote_adaptive(
                    "turn-source", "Project state: green", stale_usage,
                    source_snapshot=snapshot,
                )
            )
            self.assertIsNone(store2.document(adaptive_id))

    def test_adaptive_promotion_failure_is_fail_open_for_recall(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace, store, _, recall = self.make_brain(root)
            config.adaptive_memory_min_sessions = 1
            config.adaptive_memory_min_days = 1
            config.adaptive_memory_min_injections = 1
            self.register_source(config, workspace, store)

            with patch.object(
                Curator,
                "promote_adaptive",
                side_effect=OSError("simulated adaptive write failure"),
            ):
                context = recall.context(
                    str(workspace),
                    "Atlas port 6432",
                    consumer_provider="codex",
                    consumer_session_id="consumer-fail-open",
                )

            self.assertIn("Project Atlas uses port 6432", context)
            self.assertIsNone(store.document(adaptive_memory_id("turn-source")))

    def test_documentation_matches_default_adaptive_memory_contract(self) -> None:
        config = BrainConfig(
            version=1,
            home="/tmp/wikibrain-doc-contract",
            vault="/tmp/wikibrain-doc-contract/vault",
            workspace_roots=[],
        )
        self.assertEqual(config.adaptive_memory_window_days, 60)
        self.assertEqual(config.adaptive_memory_min_sessions, 3)
        self.assertEqual(config.adaptive_memory_min_days, 3)
        self.assertEqual(config.adaptive_memory_min_injections, 2)
        self.assertEqual(config.adaptive_memory_max_chars, 2_000)

        root = Path(__file__).resolve().parents[1]
        expected = {
            "README.md": ("rolling 60-day", "provider/session", "2,000"),
            "README.ko.md": ("최근 60일", "provider/session", "2,000"),
            "README.ja.md": ("直近 60 日", "provider/session", "2,000"),
            "README.zh-CN.md": ("最近 60 天", "provider/session", "2,000"),
        }
        for relative_path, markers in expected.items():
            content = (root / relative_path).read_text(encoding="utf-8")
            for marker in markers:
                self.assertIn(marker, content, relative_path)
        architecture = (root / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn("Schema v9", architecture)
        self.assertIn("three distinct consumer provider/session", architecture)
        self.assertIn(
            "manual recalls without a consumer identity do not\ncount", architecture
        )


if __name__ == "__main__":
    unittest.main()
