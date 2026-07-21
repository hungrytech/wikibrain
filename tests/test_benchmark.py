from __future__ import annotations

import json
import runpy
import subprocess
import sys
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
file_sha256: Callable[[Path], str] = BENCHMARK_GLOBALS["_file_sha256"]
source_manifest_sha256: Callable[[], str] = BENCHMARK_GLOBALS[
    "source_manifest_sha256"
]


class SecondBrainBenchmarkTests(unittest.TestCase):
    def test_committed_benchmark_chart_is_current(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/render_benchmark_chart.py", "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_chart_distinguishes_failed_checks_without_color_alone(self) -> None:
        result_path = ROOT / "benchmarks" / "results" / "second-brain-v1.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["cases"][0]["passed"] = False
        renderer = runpy.run_path(
            str(ROOT / "scripts" / "render_benchmark_chart.py")
        )["render_chart"]

        svg = renderer(result)

        self.assertIn("Failed checks: Current decision.", svg)
        self.assertIn('stroke="#ffffff"', svg)

    def test_readme_benchmark_values_match_committed_result(self) -> None:
        result_path = ROOT / "benchmarks" / "results" / "second-brain-v1.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        p50 = float(result["latency_ms"]["p50"])
        p95 = float(result["latency_ms"]["p95"])
        passed = int(result["checks_passed"])
        total = int(result["checks_total"])

        expected_values = (f"{p50:.2f}", f"{p95:.2f}", f"{passed}/{total}")
        for readme_name in (
            "README.md",
            "README.ko.md",
            "README.ja.md",
            "README.zh-CN.md",
        ):
            readme = (ROOT / readme_name).read_text(encoding="utf-8")
            with self.subTest(readme=readme_name):
                for value in expected_values:
                    self.assertIn(value, readme)

    def test_readme_navigation_and_sections_are_in_sync(self) -> None:
        readme_names = (
            "README.md",
            "README.ko.md",
            "README.ja.md",
            "README.zh-CN.md",
        )
        anchor_ids = (
            "why-wikibrain",
            "getting-started",
            "how-it-works",
            "verified-benchmark",
            "installation-and-trust",
            "native-windows",
            "daily-commands",
            "data-and-privacy",
            "project-documentation",
        )
        language_targets = set(readme_names)

        for readme_name in readme_names:
            readme = (ROOT / readme_name).read_text(encoding="utf-8")
            with self.subTest(readme=readme_name):
                for anchor_id in anchor_ids:
                    self.assertEqual(readme.count(f'id="{anchor_id}"'), 1)
                    self.assertIn(f"](#{anchor_id})", readme)
                for target in language_targets - {readme_name}:
                    self.assertIn(f'href="{target}"', readme)

    def test_deterministic_functional_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = run_benchmark(
                root=Path(temporary),
                wikimap_command=str(FAKE_WIKIMAP),
                latency_iterations=2,
            )

        self.assertEqual(result["score_percent"], 100.0)
        self.assertEqual(result["retrieval_mode"], "mixed-contract")
        self.assertEqual(
            result["retrieval_modes"],
            {
                "query_checks": "query-only-no-recent-fallback",
                "handoff_check": "session-start-recent-context",
            },
        )
        self.assertEqual(result["checks_passed"], result["checks_total"])
        self.assertGreaterEqual(result["corpus_documents"], 6)
        self.assertGreater(result["latency_ms"]["p50"], 0)
        self.assertTrue(all(case["passed"] for case in result["cases"]))

    def test_provenance_hash_normalizes_checkout_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lf = root / "lf.txt"
            crlf = root / "crlf.txt"
            lf.write_bytes(b"alpha\nbeta\n")
            crlf.write_bytes(b"alpha\r\nbeta\r\n")
            self.assertEqual(file_sha256(lf), file_sha256(crlf))

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
            provenance["runner_sha256"], file_sha256(runner)
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
