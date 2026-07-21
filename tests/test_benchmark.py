from __future__ import annotations

import hashlib
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
FAKE_WIKIMAP = ROOT / "tests" / "fixtures" / "fake_wikimap.py"
BENCHMARK_GLOBALS = runpy.run_path(
    str(ROOT / "benchmarks" / "second_brain.py")
)
run_benchmark: Callable[..., dict[str, Any]] = BENCHMARK_GLOBALS["run_benchmark"]
source_manifest_sha256: Callable[[], str] = BENCHMARK_GLOBALS[
    "source_manifest_sha256"
]


class SecondBrainBenchmarkTests(unittest.TestCase):
    def test_deterministic_functional_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = run_benchmark(
                root=Path(temporary),
                wikimap_command=str(FAKE_WIKIMAP),
                latency_iterations=2,
            )

        self.assertEqual(result["score_percent"], 100.0)
        self.assertEqual(result["retrieval_mode"], "query-only")
        self.assertEqual(result["checks_passed"], result["checks_total"])
        self.assertGreaterEqual(result["corpus_documents"], 6)
        self.assertGreater(result["latency_ms"]["p50"], 0)
        self.assertTrue(all(case["passed"] for case in result["cases"]))

    def test_committed_result_has_verifiable_provenance(self) -> None:
        runner = ROOT / "benchmarks" / "second_brain.py"
        result_path = ROOT / "benchmarks" / "results" / "second-brain-v1.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        provenance = result["provenance"]

        self.assertEqual(provenance["corpus_version"], "second-brain-corpus-v1")
        self.assertEqual(provenance["latency_iterations"], 20)
        self.assertEqual(provenance["latency_queries"], 4)
        self.assertEqual(result["latency_ms"]["samples"], 80)
        self.assertEqual(
            provenance["runner_sha256"], hashlib.sha256(runner.read_bytes()).hexdigest()
        )
        self.assertEqual(
            provenance["source_manifest_sha256"], source_manifest_sha256()
        )
        self.assertRegex(provenance["git_commit"], r"^[0-9a-f]{40}$")
        self.assertIn("--iterations 20", provenance["reproduction_command"])
        self.assertRegex(
            provenance["generated_at"], r"^\d{4}-\d{2}-\d{2}T.*\+00:00$"
        )


if __name__ == "__main__":
    unittest.main()
