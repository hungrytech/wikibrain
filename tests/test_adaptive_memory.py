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
from threading import Barrier, Event, Lock
from unittest.mock import patch

from wikibrain.config import BrainConfig
from wikibrain.cli import command_forget
from wikibrain.curation import Curator
from wikibrain.hooks import process_hook
from wikibrain.models import SearchHit
from wikibrain.recall import RecallService
from wikibrain.storage import (
    BrainStore,
    adaptive_memory_id,
    adaptive_promotion_score,
)
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
            fourth = store.record_document_usage(
                "turn-source",
                consumer_provider="codex",
                consumer_session_id="consumer-4",
                searched=True,
                injected=True,
                used_at=(base + timedelta(days=3)).isoformat(),
                window_days=60,
                min_sessions=3,
                min_days=3,
                min_injections=2,
            )

            self.assertFalse(first["eligible"])
            self.assertEqual(replay["distinct_sessions"], 1)
            self.assertEqual(second["distinct_days"], 2)
            self.assertTrue(third["hard_gate_met"])
            self.assertFalse(third["eligible"])
            self.assertTrue(fourth["eligible"])
            self.assertEqual(fourth["distinct_sessions"], 4)
            self.assertEqual(fourth["distinct_days"], 4)
            self.assertEqual(fourth["context_injections"], 4)
            with store.connect() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM document_usage").fetchone()[0],
                    4,
                )

    def test_score_blocks_bare_hard_gate_until_usage_is_broad_enough(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace, store, _, _ = self.make_brain(root)
            self.register_source(config, workspace, store)
            base = datetime(2026, 6, 1, tzinfo=UTC)
            usages = [
                ("claude", "consumer-1", 0, True),
                ("codex", "consumer-2", 1, True),
                ("claude", "consumer-3", 2, False),
            ]
            stats = {}
            for provider, session_id, day, searched in usages:
                stats = store.record_document_usage(
                    "turn-source",
                    consumer_provider=provider,
                    consumer_session_id=session_id,
                    searched=searched,
                    injected=True,
                    used_at=(base + timedelta(days=day)).isoformat(),
                    window_days=60,
                    min_sessions=3,
                    min_days=3,
                    min_injections=2,
                    min_score=0.65,
                )

            self.assertTrue(stats["hard_gate_met"])
            self.assertFalse(stats["eligible"])
            self.assertLess(stats["promotion_score"], 0.65)
            self.assertEqual(stats["promotion_score_threshold"], 0.65)
            self.assertEqual(stats["distinct_providers"], 2)
            self.assertEqual(
                stats["promotion_score_components"],
                {
                    "session_diversity": 0.15,
                    "day_persistence": 0.125,
                    "injection_recurrence": 0.1875,
                    "query_backed_ratio": 0.066667,
                    "provider_diversity": 0.1,
                },
            )
            self.assertEqual(stats["promotion_score"], 0.629167)
            self.assertAlmostEqual(
                sum(stats["promotion_score_components"].values()),
                stats["promotion_score"],
            )

    def test_score_boundary_is_deterministic(self) -> None:
        score, components = adaptive_promotion_score(
            distinct_sessions=3,
            distinct_providers=1,
            distinct_days=4,
            search_sessions=1,
            context_injections=4,
            min_sessions=3,
            min_days=3,
            min_injections=2,
        )
        self.assertEqual(score, 0.65)
        self.assertEqual(round(sum(components.values()), 6), 0.65)

    def test_search_only_and_later_injection_do_not_synthesize_query_credit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config, workspace, store, _, _ = self.make_brain(Path(temporary))
            self.register_source(config, workspace, store)
            common = {
                "consumer_provider": "claude",
                "consumer_session_id": "session-a",
                "used_at": "2026-07-01T09:00:00+00:00",
                "min_sessions": 1,
                "min_days": 1,
                "min_injections": 1,
                "min_score": 0,
            }

            first = store.record_document_usage(
                "turn-source", searched=True, injected=False, **common
            )
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE document_usage SET searched = 1 WHERE document_id = ?",
                    ("turn-source",),
                )
            second = store.record_document_usage(
                "turn-source", searched=False, injected=True, **common
            )

            self.assertEqual(first["search_sessions"], 0)
            self.assertEqual(second["search_sessions"], 0)
            self.assertEqual(second["context_injections"], 1)
            self.assertEqual(
                second["promotion_score_components"]["query_backed_ratio"], 0.0
            )

    def test_non_injected_usage_does_not_raise_promotion_score(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace, store, _, _ = self.make_brain(root)
            self.register_source(config, workspace, store)

            stats = store.record_document_usage(
                "turn-source",
                consumer_provider="claude",
                consumer_session_id="search-only",
                searched=True,
                injected=False,
                used_at="2026-06-01T00:00:00+00:00",
            )

            self.assertEqual(stats["distinct_sessions"], 0)
            self.assertEqual(stats["distinct_providers"], 0)
            self.assertEqual(stats["distinct_days"], 0)
            self.assertEqual(stats["search_sessions"], 0)
            self.assertEqual(stats["context_injections"], 0)
            self.assertEqual(stats["promotion_score"], 0)
            self.assertFalse(stats["hard_gate_met"])

    def test_score_threshold_must_be_between_zero_and_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace, store, _, _ = self.make_brain(root)
            self.register_source(config, workspace, store)

            for threshold in (-0.01, 1.01):
                with self.subTest(threshold=threshold):
                    with self.assertRaisesRegex(ValueError, "between 0 and 1"):
                        store.record_document_usage(
                            "turn-source",
                            consumer_provider="claude",
                            consumer_session_id="consumer-1",
                            searched=True,
                            injected=True,
                            min_score=threshold,
                        )

    def test_only_direct_search_hits_are_query_backed_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config, workspace, store, _, recall = self.make_brain(Path(temporary))
            direct_path = self.register_source(config, workspace, store)
            related_path = self.register_source(
                config, workspace, store, document_id="turn-related"
            )
            recent_path = self.register_source(
                config, workspace, store, document_id="turn-recent"
            )
            store.register_document(
                "turn-source",
                "session",
                direct_path,
                provider="claude",
                session_id="source-session",
                turn_key="source-turn",
                workspace=str(workspace.resolve()),
                metadata={"captured_at": "2026-01-01T00:00:00+00:00"},
                relations={"relates-to": ["turn-related"]},
            )
            direct_row = store.document("turn-source")
            recent_row = store.document("turn-recent")
            assert direct_row is not None and recent_row is not None
            usage_calls: list[tuple[str, bool]] = []

            def record_usage(document_id: str, **kwargs):
                usage_calls.append((document_id, bool(kwargs["searched"])))
                return {"eligible": False}

            direct_hit = SearchHit(
                path=str(direct_path.relative_to(config.vault_path)),
                line=1,
                title="direct",
                snippet="Project Atlas",
                score=1.0,
                kind="session",
            )
            with (
                patch.object(recall, "search", return_value=([(direct_hit, direct_row)], "fake")),
                patch.object(store, "recent_documents", return_value=[recent_row]),
                patch.object(store, "record_document_usage", side_effect=record_usage),
            ):
                rendered = recall.context(
                    str(workspace),
                    "Project Atlas",
                    consumer_provider="codex",
                    consumer_session_id="consumer",
                )

            self.assertIn(str(related_path.relative_to(config.vault_path)), rendered)
            self.assertIn(str(recent_path.relative_to(config.vault_path)), rendered)
            self.assertCountEqual(
                usage_calls,
                [
                    ("turn-source", True),
                    ("turn-related", False),
                    ("turn-recent", False),
                ],
            )

    def test_recall_promotes_only_injected_raw_evidence_and_not_memory_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, workspace, store, _, recall = self.make_brain(root)
            source_path = self.register_source(config, workspace, store)
            config.adaptive_memory_min_sessions = 1
            config.adaptive_memory_min_days = 1
            config.adaptive_memory_min_injections = 1
            config.adaptive_memory_min_score = 0

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
            self.assertEqual(metadata["promotion_score"], 0.55)
            self.assertEqual(metadata["promotion_score_threshold"], 0)
            self.assertEqual(
                set(metadata["promotion_score_components"]),
                {
                    "session_diversity",
                    "day_persistence",
                    "injection_recurrence",
                    "query_backed_ratio",
                    "provider_diversity",
                },
            )
            memory_path = Path(str(memory["path"]))
            self.assertTrue(memory_path.is_file())
            memory_content = memory_path.read_text(encoding="utf-8")
            self.assertIn("Project Atlas uses port 6432", memory_content)
            self.assertIn("Promotion score: 0.550 / 0.000", memory_content)
            self.assertLessEqual(len(memory_content), 4_000)

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

            usages = [
                {
                    "distinct_sessions": 3,
                    "distinct_days": 3,
                    "search_sessions": 3,
                    "context_injections": 3,
                    "last_used_at": "2026-06-03T00:00:00+00:00",
                    "promotion_score": 0.61,
                },
                {
                    "distinct_sessions": 4,
                    "distinct_days": 4,
                    "search_sessions": 4,
                    "context_injections": 4,
                    "last_used_at": "2026-06-04T00:00:00+00:00",
                    "promotion_score": 0.79,
                },
            ]
            with patch.object(store, "document", side_effect=synchronized_document):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(
                        executor.map(
                            lambda candidate: curator.promote_adaptive(
                                "turn-source", candidate[0], candidate[1]
                            ),
                            zip(["Alpha evidence", "Beta evidence"], usages),
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
            metadata = json.loads(str(registered["metadata_json"]))
            markdown = only_path.read_text(encoding="utf-8")
            if "Alpha evidence" in markdown:
                self.assertNotIn("Beta evidence", markdown)
                self.assertEqual(metadata["promotion_score"], 0.61)
            else:
                self.assertIn("Beta evidence", markdown)
                self.assertNotIn("Alpha evidence", markdown)
                self.assertEqual(metadata["promotion_score"], 0.79)

    def test_adaptive_publish_failure_rolls_back_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config, workspace, store, curator, _ = self.make_brain(Path(temporary))
            self.register_source(config, workspace, store)
            memory_id = adaptive_memory_id("turn-source")
            original_write = curator._write

            def write_then_fail(relative: Path, content: str) -> Path:
                path = original_write(relative, content)
                self.assertTrue(path.exists())
                raise OSError("simulated failure after atomic replace")

            with patch.object(curator, "_write", side_effect=write_then_fail):
                with self.assertRaises(OSError):
                    curator.promote_adaptive(
                        "turn-source",
                        "Project state: green",
                        {
                            "distinct_sessions": 4,
                            "distinct_days": 4,
                            "search_sessions": 4,
                            "context_injections": 4,
                            "promotion_score": 0.79,
                            "promotion_score_threshold": 0.65,
                        },
                    )

            self.assertIsNone(store.document(memory_id))
            self.assertFalse(any((config.vault_path / "memories").rglob("*.md")))

    def test_failed_publisher_cannot_delete_concurrent_winner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config, workspace, store, curator, _ = self.make_brain(Path(temporary))
            self.register_source(config, workspace, store)
            first_written = Event()
            second_attempting = Event()
            original_write = curator._write
            alpha_usage = {
                "distinct_sessions": 3,
                "distinct_days": 3,
                "search_sessions": 1,
                "context_injections": 3,
                "promotion_score": 0.61,
                "promotion_score_threshold": 0.65,
            }
            beta_usage = {
                "distinct_sessions": 5,
                "distinct_days": 5,
                "search_sessions": 5,
                "context_injections": 5,
                "promotion_score": 0.79,
                "promotion_score_threshold": 0.65,
            }

            def controlled_write(relative: Path, content: str) -> Path:
                path = original_write(relative, content)
                if "Alpha evidence" in content:
                    first_written.set()
                    self.assertTrue(second_attempting.wait(timeout=1))
                    raise OSError("failure after alpha replace")
                return path

            def publish_alpha() -> None:
                with self.assertRaises(OSError):
                    curator.promote_adaptive(
                        "turn-source", "Alpha evidence", alpha_usage
                    )

            def publish_beta() -> tuple[str, Path] | None:
                self.assertTrue(first_written.wait(timeout=1))
                second_attempting.set()
                return curator.promote_adaptive(
                    "turn-source", "Beta evidence", beta_usage
                )

            with patch.object(curator, "_write", side_effect=controlled_write):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    alpha_future = executor.submit(publish_alpha)
                    beta_future = executor.submit(publish_beta)
                    alpha_future.result()
                    beta_result = beta_future.result()

            self.assertIsNotNone(beta_result)
            memory_id = adaptive_memory_id("turn-source")
            registered = store.document(memory_id)
            self.assertIsNotNone(registered)
            assert registered is not None
            path = Path(str(registered["path"]))
            self.assertTrue(path.exists())
            markdown = path.read_text(encoding="utf-8")
            metadata = json.loads(str(registered["metadata_json"]))
            self.assertIn("Beta evidence", markdown)
            self.assertNotIn("Alpha evidence", markdown)
            self.assertEqual(metadata["promotion_score"], 0.79)

    def test_two_failed_publishers_leave_no_orphan_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config, workspace, store, curator, _ = self.make_brain(Path(temporary))
            self.register_source(config, workspace, store)
            first_written = Event()
            second_attempting = Event()
            original_write = curator._write
            usage = {
                "distinct_sessions": 4,
                "distinct_days": 4,
                "search_sessions": 4,
                "context_injections": 4,
                "promotion_score": 0.79,
                "promotion_score_threshold": 0.65,
            }

            def controlled_write(relative: Path, content: str) -> Path:
                original_write(relative, content)
                if "Alpha evidence" in content:
                    first_written.set()
                    self.assertTrue(second_attempting.wait(timeout=1))
                raise OSError(f"failure after replace: {content}")

            def publish_alpha() -> None:
                with self.assertRaises(OSError):
                    curator.promote_adaptive(
                        "turn-source", "Alpha evidence", usage
                    )

            def publish_beta() -> None:
                self.assertTrue(first_written.wait(timeout=1))
                second_attempting.set()
                with self.assertRaises(OSError):
                    curator.promote_adaptive(
                        "turn-source", "Beta evidence", usage
                    )

            with patch.object(curator, "_write", side_effect=controlled_write):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    alpha_future = executor.submit(publish_alpha)
                    beta_future = executor.submit(publish_beta)
                    alpha_future.result()
                    beta_future.result()

            self.assertIsNone(store.document(adaptive_memory_id("turn-source")))
            self.assertFalse(any((config.vault_path / "memories").rglob("*.md")))

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
            config.adaptive_memory_min_score = 0
            self.register_source(config, workspace, store)

            with patch.object(
                Curator,
                "promote_adaptive",
                side_effect=OSError("simulated adaptive write failure"),
            ) as promote:
                context = recall.context(
                    str(workspace),
                    "Atlas port 6432",
                    consumer_provider="codex",
                    consumer_session_id="consumer-fail-open",
                )

            promote.assert_called_once()
            self.assertIn("Project Atlas uses port 6432", context)
            self.assertIsNone(store.document(adaptive_memory_id("turn-source")))

    def test_legacy_config_without_score_uses_default_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "brain"
            config = BrainConfig.create(home)
            payload = json.loads(config.config_path.read_text(encoding="utf-8"))
            payload.pop("adaptive_memory_min_score")
            config.config_path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = BrainConfig.load(home)

            self.assertEqual(loaded.adaptive_memory_min_score, 0.65)

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
        self.assertEqual(config.adaptive_memory_min_score, 0.65)
        self.assertEqual(config.adaptive_memory_max_chars, 2_000)

        root = Path(__file__).resolve().parents[1]
        expected = {
            "README.md": ("rolling 60-day", "provider/session", "0.65", "2,000"),
            "README.ko.md": ("최근 60일", "provider/session", "0.65", "2,000"),
            "README.ja.md": ("直近 60 日", "provider/session", "0.65", "2,000"),
            "README.zh-CN.md": ("最近 60 天", "provider/session", "0.65", "2,000"),
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
