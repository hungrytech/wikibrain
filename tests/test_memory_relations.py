from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import yaml

from wikibrain.cli import main
from wikibrain.config import BrainConfig
from wikibrain.curation import Curator
from wikibrain.models import SearchHit
from wikibrain.recall import RecallService
from wikibrain.storage import BrainStore
from wikibrain.wikimap_adapter import WikimapAdapter


ROOT = Path(__file__).resolve().parents[1]
FAKE_WIKIMAP = ROOT / "tests" / "fixtures" / "fake_wikimap.py"


class MemoryRelationTests(unittest.TestCase):
    def make_brain(self, root: Path, workspace_roots: list[Path]):
        config = BrainConfig.create(
            root / "brain",
            root / "brain" / "vault",
            workspace_roots,
        )
        config.wikimap_command = str(FAKE_WIKIMAP)
        config.save()
        store = BrainStore(config.database_path)
        curator = Curator(
            config,
            store,
            WikimapAdapter(config.vault_path, str(FAKE_WIKIMAP)),
        )
        return config, store, curator

    def test_superseded_memory_is_hidden_and_relation_is_recalled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "project"
            workspace.mkdir()
            config, store, curator = self.make_brain(root, [workspace])

            evidence_id, _ = curator.remember(
                "The repository has a uv.lock file and CI runs uv sync.",
                title="Package manager evidence",
                workspace=str(workspace),
            )
            old_id, _ = curator.remember(
                "Package manager decision: use pip for project commands.",
                title="Package manager decision",
                workspace=str(workspace),
            )
            new_id, new_path = curator.remember(
                "Package manager decision: use uv for project commands.",
                title="Package manager decision",
                workspace=str(workspace),
                relates_to=[evidence_id],
                supersedes=[old_id],
            )

            context = RecallService(
                config,
                store,
                WikimapAdapter(config.vault_path, str(FAKE_WIKIMAP)),
            ).context(str(workspace), "package manager decision")

            self.assertIn("use uv", context)
            self.assertNotIn("use pip", context)
            self.assertIn(f'document_id="{evidence_id}"', context)
            self.assertIn(f'document_id="{old_id}"', context)
            self.assertIn('type="relates-to"', context)
            self.assertIn('type="supersedes"', context)
            self.assertEqual(
                {
                    (row["relation_type"], row["target_document_id"])
                    for row in store.document_relations(new_id)
                },
                {("relates-to", evidence_id), ("supersedes", old_id)},
            )
            markdown = new_path.read_text(encoding="utf-8")
            self.assertIn(f'relates_to: ["{evidence_id}"]', markdown)
            self.assertIn(f'supersedes: ["{old_id}"]', markdown)

    def test_relation_cannot_cross_project_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_a = root / "project-a"
            project_b = root / "project-b"
            project_a.mkdir()
            project_b.mkdir()
            config, store, curator = self.make_brain(root, [project_a, project_b])

            foreign_id, _ = curator.remember(
                "Project A private architecture.",
                workspace=str(project_a),
            )
            before = store.document_count()
            with self.assertRaisesRegex(ValueError, "relation target.*workspace"):
                curator.remember(
                    "Project B decision.",
                    workspace=str(project_b),
                    relates_to=[foreign_id],
                )
            self.assertEqual(store.document_count(), before)
            self.assertEqual(
                list(config.vault_path.rglob("*Project-B-decision*.md")), []
            )

    def test_remember_cli_accepts_relation_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "project"
            workspace.mkdir()
            config, _, curator = self.make_brain(root, [workspace])
            old_id, _ = curator.remember(
                "Use the old endpoint.",
                workspace=str(workspace),
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--home",
                        str(config.home_path),
                        "remember",
                        "Use the new endpoint.",
                        "--workspace",
                        str(workspace),
                        "--supersedes",
                        old_id,
                        "--relates-to",
                        old_id,
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["relations"]["supersedes"], [old_id])
            self.assertEqual(payload["relations"]["relates_to"], [old_id])

    def test_forget_removes_incoming_relation_from_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "project"
            workspace.mkdir()
            config, _, curator = self.make_brain(root, [workspace])
            target_id, _ = curator.remember(
                "Supporting evidence.", workspace=str(workspace)
            )
            _, source_path = curator.remember(
                "Current decision.",
                workspace=str(workspace),
                relates_to=[target_id],
            )

            with redirect_stdout(StringIO()):
                code = main(
                    [
                        "--home",
                        str(config.home_path),
                        "forget",
                        "--document",
                        target_id,
                        "--apply",
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertNotIn(
                target_id, source_path.read_text(encoding="utf-8")
            )

    def test_retention_retries_multiline_yaml_relation_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "project"
            workspace.mkdir()
            config, store, curator = self.make_brain(root, [workspace])
            target_id, _ = curator.remember(
                "Expired supporting evidence.", workspace=str(workspace)
            )
            _, source_path = curator.remember(
                "Current decision.",
                workspace=str(workspace),
                relates_to=[target_id],
                supersedes=[target_id],
            )
            text = source_path.read_text(encoding="utf-8")
            text = text.replace(
                f'relates_to: ["{target_id}"]',
                f"relates_to:\n  - '{target_id}'",
            ).replace(
                f'supersedes: ["{target_id}"]',
                f"supersedes: [ '{target_id}' ]",
            )
            source_path.write_text(text, encoding="utf-8")
            with store.connect() as connection:
                connection.execute(
                    """
                    UPDATE documents SET kind = 'handoff', created_at = ?
                    WHERE document_id = ?
                    """,
                    ("2000-01-01T00:00:00+00:00", target_id),
                )

            arguments = [
                "--home",
                str(config.home_path),
                "retention",
                "--days",
                "1",
                "--apply",
                "--json",
            ]
            with mock.patch.object(
                Curator,
                "remove_relation_target",
                side_effect=OSError("simulated cleanup failure"),
            ):
                with redirect_stdout(StringIO()):
                    first_code = main(arguments)

            self.assertEqual(first_code, 1)
            self.assertIsNone(store.document(target_id))
            self.assertIn(target_id, source_path.read_text(encoding="utf-8"))
            self.assertEqual(len(store.pending_relation_cleanups()), 1)

            with redirect_stdout(StringIO()):
                retry_code = main(arguments)

            self.assertEqual(retry_code, 0)
            updated = source_path.read_text(encoding="utf-8")
            self.assertNotIn(target_id, updated)
            frontmatter = updated.split("---\n", 2)[1]
            metadata = yaml.safe_load(frontmatter)
            self.assertEqual(metadata["relates_to"], [])
            self.assertEqual(metadata["supersedes"], [])
            self.assertIn("# Current decision", updated)
            self.assertEqual(store.pending_relation_cleanups(), [])

    def test_forgetting_superseder_does_not_revive_stale_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "project"
            workspace.mkdir()
            config, store, curator = self.make_brain(root, [workspace])
            old_id, _ = curator.remember(
                "OLDMARK: use the retired endpoint.",
                workspace=str(workspace),
            )
            new_id, new_path = curator.remember(
                "NEWMARK: use the current endpoint.",
                workspace=str(workspace),
                supersedes=[old_id],
            )

            new_path.unlink()
            store.forget_document(new_id, "test deletion")
            curator.update_index()
            context = RecallService(
                config,
                store,
                WikimapAdapter(config.vault_path, str(FAKE_WIKIMAP)),
            ).context(str(workspace), "endpoint")

            self.assertNotIn("OLDMARK", context)
            self.assertTrue(store.document_is_superseded(old_id))

    def test_search_hit_keeps_a_late_matching_snippet(self) -> None:
        class FixedSearch:
            def __init__(self, path: Path):
                self.path = path

            def search(self, query: str, limit: int = 8):
                del query, limit
                return [
                    SearchHit(
                        path=str(self.path),
                        line=80,
                        title="Late evidence",
                        snippet="UNIQUE-LATE-MATCH",
                        score=1.0,
                        kind="memory",
                    )
                ]

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "project"
            workspace.mkdir()
            config, store, curator = self.make_brain(root, [workspace])
            _, path = curator.remember(
                ("leading context " * 100) + "UNIQUE-LATE-MATCH",
                workspace=str(workspace),
            )

            context = RecallService(
                config,
                store,
                FixedSearch(path),  # type: ignore[arg-type]
            ).context(str(workspace), "UNIQUE-LATE-MATCH")

            self.assertIn("UNIQUE-LATE-MATCH", context)

    def test_related_evidence_never_exceeds_result_limit(self) -> None:
        class FixedSearch:
            def __init__(self, path: Path):
                self.path = path

            def search(self, query: str, limit: int = 8):
                del query, limit
                return [
                    SearchHit(
                        path=str(self.path),
                        line=1,
                        title="Decision",
                        snippet="LIMIT-MARKER",
                        score=1.0,
                        kind="memory",
                    )
                ]

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "project"
            workspace.mkdir()
            config, store, curator = self.make_brain(root, [workspace])
            evidence_id, _ = curator.remember(
                "Supporting LIMIT-EVIDENCE.", workspace=str(workspace)
            )
            _, source_path = curator.remember(
                "Decision LIMIT-MARKER.",
                workspace=str(workspace),
                relates_to=[evidence_id],
            )
            config.recall_result_limit = 1

            context = RecallService(
                config,
                store,
                FixedSearch(source_path),  # type: ignore[arg-type]
            ).context(str(workspace), "LIMIT-MARKER")

            self.assertEqual(context.count('<record index="'), 1)
            self.assertNotIn("LIMIT-EVIDENCE", context)

    def test_related_document_cannot_be_moved_to_another_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_a = root / "project-a"
            project_b = root / "project-b"
            project_a.mkdir()
            project_b.mkdir()
            config, store, curator = self.make_brain(root, [project_a, project_b])
            target_id, target_path = curator.remember(
                "Project A evidence.", workspace=str(project_a)
            )
            source_id, source_path = curator.remember(
                "Project A decision.",
                workspace=str(project_a),
                relates_to=[target_id],
            )

            for document_id, path in (
                (source_id, source_path),
                (target_id, target_path),
            ):
                with self.subTest(document_id=document_id):
                    with self.assertRaisesRegex(ValueError, "workspace cannot change"):
                        store.register_document(
                            document_id,
                            "memory",
                            path,
                            workspace=str(config.scope_for(str(project_b))),
                        )
                    row = store.document(document_id)
                    self.assertIsNotNone(row)
                    assert row is not None
                    self.assertEqual(
                        row["workspace"],
                        str(config.scope_for(str(project_a))),
                    )

    def test_supersession_cycle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "project"
            workspace.mkdir()
            config, store, curator = self.make_brain(root, [workspace])
            first_id, first_path = curator.remember(
                "First decision.", workspace=str(workspace)
            )
            second_id, _ = curator.remember(
                "Second decision.",
                workspace=str(workspace),
                supersedes=[first_id],
            )

            with self.assertRaisesRegex(ValueError, "cycle"):
                store.register_document(
                    first_id,
                    "memory",
                    first_path,
                    workspace=str(config.scope_for(str(workspace))),
                    relations={"supersedes": [second_id]},
                )

    def test_schema_v4_is_upgraded_without_losing_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "project"
            workspace.mkdir()
            config, store, curator = self.make_brain(root, [workspace])
            document_id, _ = curator.remember(
                "Migration marker.", workspace=str(workspace)
            )
            with store.connect() as connection:
                connection.execute("DROP TABLE supersession_tombstones")
                connection.execute(
                    "UPDATE metadata SET value = '4' WHERE key = 'schema_version'"
                )

            migrated = BrainStore(config.database_path)
            with migrated.connect() as connection:
                version = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'schema_version'"
                ).fetchone()[0]
                table = connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'supersession_tombstones'
                    """
                ).fetchone()
            self.assertEqual(version, "6")
            self.assertIsNotNone(table)
            self.assertIsNotNone(migrated.document(document_id))

    def test_future_schema_is_rejected_without_downgrade(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "brain.db"
            store = BrainStore(path)
            with store.connect() as connection:
                connection.execute(
                    "UPDATE metadata SET value = '999' WHERE key = 'schema_version'"
                )

            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                BrainStore(path)
            with closing(sqlite3.connect(path)) as connection:
                version = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'schema_version'"
                ).fetchone()[0]
            self.assertEqual(version, "999")

    def test_v5_migration_backfills_cleanup_from_tombstone_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "project"
            workspace.mkdir()
            config, store, curator = self.make_brain(root, [workspace])
            target_id, _ = curator.remember("Old evidence", workspace=str(workspace))
            _, source_path = curator.remember(
                "Current decision",
                workspace=str(workspace),
                relates_to=[target_id],
            )
            store.forget_document(target_id, "simulate-v5-crash")
            with store.connect() as connection:
                connection.execute("DELETE FROM relation_cleanup_outbox")
                connection.execute(
                    "UPDATE metadata SET value = '5' WHERE key = 'schema_version'"
                )

            migrated = BrainStore(config.database_path)
            pending = migrated.pending_relation_cleanups()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["source_path"], str(source_path))
            self.assertEqual(pending[0]["target_document_id"], target_id)

    def test_malformed_existing_table_does_not_advance_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "brain.db"
            store = BrainStore(path)
            with store.connect() as connection:
                connection.execute("DROP TABLE supersession_tombstones")
                connection.execute(
                    "CREATE TABLE supersession_tombstones (wrong_column TEXT)"
                )
                connection.execute(
                    "UPDATE metadata SET value = '4' WHERE key = 'schema_version'"
                )

            with self.assertRaisesRegex(RuntimeError, "invalid schema"):
                BrainStore(path)
            with closing(sqlite3.connect(path)) as connection:
                version = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'schema_version'"
                ).fetchone()[0]
            self.assertEqual(version, "4")


if __name__ == "__main__":
    unittest.main()
