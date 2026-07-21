from __future__ import annotations

import json
import math
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmarks.retrieval_quality import (
    _sha256,
    _source_manifest_sha256,
    derive_forbidden,
    run_quality_benchmark,
    score_rankings,
    validate_corpus,
)


ROOT = Path(__file__).resolve().parents[1]


class RetrievalQualityCorpusValidationTests(unittest.TestCase):
    def test_rejects_duplicate_document_ids(self) -> None:
        corpus = {
            "corpus_version": "v1",
            "documents": [{"id": "same"}, {"id": "same"}],
            "queries": [],
        }
        with self.assertRaisesRegex(ValueError, "duplicate document id"):
            validate_corpus(corpus)

    def test_rejects_unknown_or_conflicting_labels(self) -> None:
        corpus = {
            "corpus_version": "v1",
            "documents": [{"id": "known", "workspace": "atlas"}],
            "queries": [
                {
                    "id": "q1",
                    "workspace": "atlas",
                    "relevant": {"missing": 3},
                    "forbidden": {"missing": "workspace"},
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "unknown document id"):
            validate_corpus(corpus)

        corpus["queries"][0]["relevant"] = {"known": 3}
        corpus["queries"][0]["forbidden"] = {"known": "workspace"}
        with self.assertRaisesRegex(ValueError, "both relevant and forbidden"):
            validate_corpus(corpus)


class RetrievalQualitySafetyLabelTests(unittest.TestCase):
    def test_derives_workspace_superseded_and_deleted_for_every_query(self) -> None:
        corpus = {
            "documents": [
                {"id": "current", "workspace": "atlas"},
                {"id": "other", "workspace": "borealis"},
                {"id": "old", "workspace": "atlas"},
                {"id": "new", "workspace": "atlas", "supersedes": ["old"]},
                {"id": "deleted", "workspace": "atlas", "delete_after_ingest": True},
                {"id": "global", "workspace": None},
            ]
        }
        query = {
            "id": "q1",
            "workspace": "atlas",
            "relevant": {"current": 3},
            "forbidden": {},
        }
        self.assertEqual(
            derive_forbidden(corpus, query),
            {"other": "workspace", "old": "superseded", "deleted": "deleted"},
        )


class RetrievalQualityMetricTests(unittest.TestCase):
    def test_scores_ranked_relevance_and_forbidden_exposure(self) -> None:
        result = score_rankings(
            [
                {
                    "query_id": "q1",
                    "relevant": {"a": 3, "b": 1},
                    "retrieved": ["workspace-leak", "a", "b"],
                    "forbidden": {"workspace-leak": "workspace"},
                },
                {
                    "query_id": "q2",
                    "relevant": {"c": 2},
                    "retrieved": ["c", "d"],
                    "forbidden": {"stale": "superseded"},
                },
            ],
            cutoffs=(1, 3),
        )

        self.assertEqual(result["query_count"], 2)
        self.assertAlmostEqual(result["recall_at_1"], 0.5)
        self.assertAlmostEqual(result["recall_at_3"], 1.0)
        self.assertAlmostEqual(result["mrr"], 0.75)
        self.assertAlmostEqual(result["ndcg_at_3"], 0.8221434631015414)
        self.assertAlmostEqual(result["top1_source_match"], 0.5)
        self.assertAlmostEqual(result["forbidden_query_rate"], 0.5)
        self.assertEqual(result["violations"], {"workspace": 1})

    def test_duplicate_retrieved_ids_cannot_inflate_ndcg(self) -> None:
        metrics = score_rankings(
            [
                {
                    "query_id": "duplicate",
                    "relevant": {"a": 3, "b": 1},
                    "retrieved": ["a", "a"],
                    "forbidden": {},
                }
            ],
            cutoffs=(1, 3),
        )
        self.assertLessEqual(metrics["ndcg_at_3"], 1.0)
        self.assertAlmostEqual(
            metrics["ndcg_at_3"],
            7 / (7 + 1 / math.log2(3)),
        )
        self.assertEqual(metrics["recall_at_3"], 0.5)

    def test_empty_retrieval_scores_zero_without_division_errors(self) -> None:
        result = score_rankings(
            [
                {
                    "query_id": "q-empty",
                    "relevant": {"expected": 1},
                    "retrieved": [],
                    "forbidden": {},
                }
            ],
            cutoffs=(1, 5),
        )

        self.assertEqual(result["recall_at_1"], 0.0)
        self.assertEqual(result["recall_at_5"], 0.0)
        self.assertEqual(result["mrr"], 0.0)
        self.assertEqual(result["ndcg_at_5"], 0.0)
        self.assertEqual(result["top1_source_match"], 0.0)
        self.assertEqual(result["forbidden_query_rate"], 0.0)


class RetrievalQualityIntegrationTests(unittest.TestCase):
    def test_ingests_corpus_and_scores_scoped_superseded_search(self) -> None:
        corpus = {
            "corpus_version": "test-v1",
            "documents": [
                {
                    "id": "old-package",
                    "workspace": "atlas",
                    "title": "Old package decision",
                    "text": "Package manager decision: use pip for Atlas.",
                    "captured_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "id": "current-package",
                    "workspace": "atlas",
                    "title": "Current package decision",
                    "text": "Package manager decision: use uv, replacing pip for Atlas.",
                    "captured_at": "2026-02-01T00:00:00+00:00",
                    "supersedes": ["old-package"],
                },
                {
                    "id": "other-workspace",
                    "workspace": "borealis",
                    "title": "Borealis package decision",
                    "text": "Package manager decision: use pip for Borealis.",
                    "captured_at": "2026-03-01T00:00:00+00:00",
                },
                {
                    "id": "deleted-draft",
                    "workspace": "atlas",
                    "title": "Deleted package draft",
                    "text": "Package manager pip replacement draft for Atlas.",
                    "captured_at": "2026-03-02T00:00:00+00:00",
                    "delete_after_ingest": True,
                },
            ],
            "queries": [
                {
                    "id": "current-decision",
                    "workspace": "atlas",
                    "text": "package manager pip replacement",
                    "relevant": {"current-package": 3},
                    "forbidden": {
                        "old-package": "superseded",
                        "other-workspace": "workspace",
                        "deleted-draft": "deleted",
                    },
                }
            ],
        }

        with TemporaryDirectory() as directory:
            result = run_quality_benchmark(
                root=Path(directory),
                corpus=corpus,
                wikimap_command=str(
                    Path(__file__).parent / "fixtures" / "fake_wikimap.py"
                ),
            )

        self.assertEqual(result["ingestion"]["requested_documents"], 4)
        self.assertEqual(result["ingestion"]["accepted_documents"], 4)
        self.assertEqual(result["ingestion"]["acceptance_rate"], 1.0)
        self.assertEqual(result["ingestion"]["source_content_presence_rate"], 1.0)
        self.assertEqual(result["ingestion"]["registered_documents"], 3)
        self.assertEqual(result["ingestion"]["deleted_documents"], 1)
        self.assertTrue(result["ingestion"]["index_clean"])
        self.assertEqual(result["quality"]["recall_at_1"], 1.0)
        self.assertEqual(result["quality"]["forbidden_query_rate"], 0.0)
        self.assertEqual(
            result["queries"][0]["retrieved"][0]["document_id"],
            "current-package",
        )
        self.assertNotIn("text", result["queries"][0])


class RetrievalQualityArtifactTests(unittest.TestCase):
    def test_committed_chart_is_current(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/render_retrieval_quality_chart.py", "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_committed_result_has_current_provenance_and_no_content(self) -> None:
        corpus_path = ROOT / "benchmarks" / "corpora" / "retrieval-quality-v1.json"
        result_path = ROOT / "benchmarks" / "results" / "retrieval-quality-v1.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(result["provenance"]["corpus_sha256"], _sha256(corpus_path))
        self.assertEqual(
            result["provenance"]["source_manifest_sha256"],
            _source_manifest_sha256(corpus_path),
        )
        self.assertRegex(result["provenance"]["git_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(result["query_engines"], {"wikimap": 12})
        self.assertEqual(result["ingestion"]["acceptance_rate"], 1.0)
        self.assertEqual(result["ingestion"]["source_content_presence_rate"], 1.0)
        self.assertTrue(result["ingestion"]["index_clean"])
        self.assertGreaterEqual(result["quality"]["recall_at_1"], 0.69)
        self.assertGreaterEqual(result["quality"]["recall_at_3"], 0.875)
        self.assertGreaterEqual(result["quality"]["mrr"], 0.875)
        self.assertEqual(result["quality"]["forbidden_query_rate"], 0.0)
        self.assertTrue(all("text" not in query for query in result["queries"]))

    def test_all_readmes_match_quality_result(self) -> None:
        result_path = ROOT / "benchmarks" / "results" / "retrieval-quality-v1.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        quality = result["quality"]
        expected = (
            f"{quality['recall_at_1'] * 100:.2f}%",
            f"{quality['recall_at_3'] * 100:.2f}%",
            f"{quality['ndcg_at_3'] * 100:.2f}%",
            f"{quality['mrr'] * 100:.2f}%",
            f"{quality['top1_source_match'] * 100:.2f}%",
            "benchmark-retrieval-quality-v1.svg",
            "retrieval-quality-v1.json",
        )
        for readme_name in (
            "README.md",
            "README.ko.md",
            "README.ja.md",
            "README.zh-CN.md",
        ):
            readme = (ROOT / readme_name).read_text(encoding="utf-8")
            with self.subTest(readme=readme_name):
                for value in expected:
                    self.assertIn(value, readme)


if __name__ == "__main__":
    unittest.main()
