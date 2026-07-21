from __future__ import annotations

import argparse
import json
import math
from html import escape
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULT = ROOT / "benchmarks" / "results" / "second-brain-v1.json"
DEFAULT_OUTPUT = ROOT / "docs" / "assets" / "benchmark-second-brain-v1.svg"

CASE_LABELS = {
    "current-decision-recall": "Current decision",
    "decision-evidence-link": "Evidence links",
    "person-project-context": "People & project",
    "source-provenance": "Source provenance",
    "workspace-isolation": "Workspace isolation",
    "secret-redaction": "Secret redaction",
    "global-preference-recall": "Global preference",
    "claude-to-codex-handoff": "Claude → Codex",
}


def _text(x: int, y: int, value: str, *, size: int = 16, weight: int = 400,
          fill: str = "#d7e1ea", anchor: str = "start") -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="ui-sans-serif, system-ui, -apple-system, '
        f'Segoe UI, sans-serif" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}">{escape(value)}</text>'
    )


def render_chart(result: dict[str, Any]) -> str:
    cases: list[dict[str, Any]] = list(result["cases"])
    latency: dict[str, Any] = dict(result["latency_ms"])
    passed = int(result["checks_passed"])
    total = int(result["checks_total"])
    p50 = float(latency["p50"])
    p95 = float(latency["p95"])
    samples = int(latency["samples"])
    failed_labels = [
        CASE_LABELS.get(str(case["name"]), str(case["name"]))
        for case in cases
        if not bool(case["passed"])
    ]
    failure_detail = (
        f" Failed checks: {', '.join(failed_labels)}."
        if failed_labels
        else " No checks failed."
    )
    axis_max = max(10, int(math.ceil(max(p50, p95) * 1.15 / 10.0) * 10))

    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="920" height="430" viewBox="0 0 920 430" role="img" aria-labelledby="title desc">',
        '<title id="title">WikiBrain second-brain benchmark</title>',
        f'<desc id="desc">{passed} of {total} functional checks passed. Recall latency was {p50:.2f} milliseconds p50 and {p95:.2f} milliseconds p95 across {samples} query samples.{failure_detail}</desc>',
        '<rect width="920" height="430" rx="24" fill="#0b1320"/>',
        '<rect x="1" y="1" width="918" height="428" rx="23" fill="none" stroke="#25364a"/>',
        _text(40, 48, "SECOND-BRAIN BENCHMARK", size=13, weight=700, fill="#7dd3fc"),
        _text(40, 82, "Retrieval quality and latency", size=26, weight=700, fill="#f8fafc"),
        _text(40, 108, "Fixed corpus · query search + SessionStart restore", size=14, fill="#8fa3b8"),
        '<rect x="40" y="132" width="392" height="228" rx="16" fill="#101d2d"/>',
        '<rect x="456" y="132" width="424" height="228" rx="16" fill="#101d2d"/>',
        _text(64, 164, "FUNCTIONAL CHECKS", size=12, weight=700, fill="#8fa3b8"),
        _text(408, 166, f"{passed}/{total}", size=22, weight=700, fill="#86efac", anchor="end"),
    ]

    for index, case in enumerate(cases):
        row = index % 4
        column = index // 4
        x = 64 + column * 174
        y = 202 + row * 38
        ok = bool(case["passed"])
        color = "#22c55e" if ok else "#ef4444"
        label = CASE_LABELS.get(str(case["name"]), str(case["name"]))
        status_mark = (
            f'<path d="M{x + 3} {y - 5} l3 3 5 -6" fill="none" stroke="#07110b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            if ok
            else f'<path d="M{x + 3} {y - 9} l8 8 M{x + 11} {y - 9} l-8 8" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round"/>'
        )
        lines.extend([
            f'<circle cx="{x + 7}" cy="{y - 5}" r="7" fill="{color}"/>',
            status_mark,
            _text(x + 22, y, label, size=13, fill="#d7e1ea"),
        ])

    lines.extend([
        _text(480, 164, "RECALL LATENCY (MS)", size=12, weight=700, fill="#8fa3b8"),
        _text(856, 164, f"{samples} samples", size=12, fill="#8fa3b8", anchor="end"),
    ])

    chart_x = 550
    chart_width = 220
    for label, value, y, color in (
        ("p50", p50, 218, "#38bdf8"),
        ("p95", p95, 286, "#a78bfa"),
    ):
        width = round(chart_width * value / axis_max)
        lines.extend([
            _text(480, y + 6, label, size=14, weight=700, fill="#d7e1ea"),
            f'<rect x="{chart_x}" y="{y - 14}" width="{chart_width}" height="24" rx="8" fill="#1e3044"/>',
            f'<rect x="{chart_x}" y="{y - 14}" width="{width}" height="24" rx="8" fill="{color}"/>',
            _text(856, y + 6, f"{value:.2f} ms", size=14, weight=700, fill="#f8fafc", anchor="end"),
        ])

    for tick in range(0, axis_max + 1, 10):
        x = chart_x + round(chart_width * tick / axis_max)
        lines.extend([
            f'<line x1="{x}" y1="320" x2="{x}" y2="326" stroke="#52677d"/>',
            _text(x, 345, str(tick), size=11, fill="#8fa3b8", anchor="middle"),
        ])
    platform = str(result["platform"]).replace("macOS-", "macOS ").replace("-arm64-arm-64bit-Mach-O", " · arm64")
    footer = f'{platform} · Python {result["python"]} · {result["engine"]}'
    lines.extend([
        '<line x1="40" y1="386" x2="880" y2="386" stroke="#25364a"/>',
        _text(40, 411, footer, size=12, fill="#8fa3b8"),
        _text(864, 411, "Lower is better", size=12, fill="#8fa3b8", anchor="end"),
        '</svg>',
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the committed benchmark chart.")
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Fail if the committed SVG is stale.")
    args = parser.parse_args()

    result = json.loads(args.result.read_text(encoding="utf-8"))
    rendered = render_chart(result)
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
            parser.error(f"{args.output} is stale; run {Path(__file__).name}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
