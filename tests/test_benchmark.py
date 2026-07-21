from __future__ import annotations

import runpy
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
FAKE_WIKIMAP = ROOT / "tests" / "fixtures" / "fake_wikimap.py"
run_benchmark: Callable[..., dict[str, Any]] = runpy.run_path(
    str(ROOT / "benchmarks" / "second_brain.py")
)["run_benchmark"]


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


if __name__ == "__main__":
    unittest.main()
