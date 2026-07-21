from __future__ import annotations

import unittest

from scripts.render_retrieval_quality_chart import render_svg


class RetrievalQualityChartTests(unittest.TestCase):
    def test_renders_quality_and_ingestion_without_private_content(self) -> None:
        svg = render_svg(
            {
                "benchmark_version": "retrieval-quality-v1",
                "corpus_version": "corpus-v1",
                "ingestion": {
                    "requested_documents": 14,
                    "accepted_documents": 14,
                    "acceptance_rate": 1.0,
                    "source_content_presence_rate": 1.0,
                    "registered_documents": 13,
                    "deleted_documents": 1,
                    "index_clean": True,
                },
                "quality": {
                    "query_count": 12,
                    "recall_at_1": 0.694444,
                    "recall_at_3": 0.875,
                    "ndcg_at_3": 0.813498,
                    "mrr": 0.875,
                    "top1_source_match": 0.833333,
                    "forbidden_query_rate": 0.0,
                    "violations": {},
                },
                "context_quality": {
                    "query_count": 12,
                    "context_recall": 0.875,
                    "context_precision": 0.791667,
                    "context_f1": 0.805556,
                    "required_atom_recall": 0.909091,
                    "forbidden_query_rate": 0.0,
                    "violations": {},
                },
                "query_engines": {"wikimap": 12},
                "wikimap_version": "wikimap 1.1.0",
            }
        )

        self.assertIn("Context recall quality", svg)
        self.assertIn("Context Recall", svg)
        self.assertIn("Context Precision", svg)
        self.assertIn("Required facts", svg)
        self.assertIn("90.91%", svg)
        self.assertIn("Retrieval Recall@3", svg)
        self.assertIn("Ingestion integrity", svg)
        self.assertIn("14 / 14", svg)
        self.assertIn("Forbidden exposure", svg)
        self.assertIn("0.00%", svg)
        self.assertIn("<title>", svg)
        self.assertIn("<desc>", svg)
        self.assertNotIn("private query text", svg)


if __name__ == "__main__":
    unittest.main()
