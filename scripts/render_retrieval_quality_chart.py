from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULT = ROOT / "benchmarks" / "results" / "retrieval-quality-v1.json"
DEFAULT_OUTPUT = ROOT / "docs" / "assets" / "benchmark-retrieval-quality-v1.svg"


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def render_svg(result: dict[str, Any]) -> str:
    quality = result["quality"]
    context_quality = result["context_quality"]
    ingestion = result["ingestion"]
    metrics = [
        ("Context Recall", float(context_quality["context_recall"])),
        ("Context Precision", float(context_quality["context_precision"])),
        ("Context F1", float(context_quality["context_f1"])),
        ("Required facts", float(context_quality["required_atom_recall"])),
        ("Retrieval Recall@3", float(quality["recall_at_3"])),
    ]
    fingerprint = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    description = (
        f"Final context quality across {context_quality['query_count']} labeled queries: "
        + ", ".join(f"{name} {_percent(value)}" for name, value in metrics)
        + f". {ingestion['accepted_documents']} of {ingestion['requested_documents']} "
        "documents were accepted; final-context forbidden exposure was "
        f"{_percent(float(context_quality['forbidden_query_rate']))}."
    )

    rows: list[str] = []
    for index, (name, value) in enumerate(metrics):
        y = 148 + index * 46
        width = max(0.0, min(1.0, value)) * 560
        rows.extend(
            [
                f'<text x="48" y="{y + 17}" class="label">{html.escape(name)}</text>',
                f'<rect x="250" y="{y}" width="560" height="24" rx="6" class="track"/>',
                f'<rect x="250" y="{y}" width="{width:.2f}" height="24" rx="6" class="bar"/>',
                f'<text x="830" y="{y + 17}" class="value">{_percent(value)}</text>',
            ]
        )

    accepted = f"{ingestion['accepted_documents']} / {ingestion['requested_documents']}"
    source_content_presence = _percent(float(ingestion["source_content_presence_rate"]))
    forbidden = _percent(float(context_quality["forbidden_query_rate"]))
    index_state = "clean" if ingestion["index_clean"] else "dirty"
    footer = (
        f"{result['corpus_version']} · {context_quality['query_count']} queries · "
        f"{result.get('wikimap_version') or 'wikimap version unavailable'} · result {fingerprint}"
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="540" viewBox="0 0 1000 540" role="img" aria-labelledby="title desc">
<title>WikiBrain context recall quality benchmark</title>
<desc>{html.escape(description)}</desc>
<style>
  .bg {{ fill: #0d1117; }}
  .panel {{ fill: #161b22; stroke: #30363d; stroke-width: 1; }}
  .title {{ fill: #f0f6fc; font: 700 30px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  .subtitle {{ fill: #8b949e; font: 14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  .section {{ fill: #c9d1d9; font: 700 16px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  .label {{ fill: #c9d1d9; font: 14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  .value {{ fill: #f0f6fc; font: 700 14px ui-monospace,SFMono-Regular,Consolas,monospace; }}
  .track {{ fill: #30363d; }}
  .bar {{ fill: #58a6ff; }}
  .card-value {{ fill: #3fb950; font: 700 21px ui-monospace,SFMono-Regular,Consolas,monospace; }}
  .card-label {{ fill: #8b949e; font: 12px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  .footer {{ fill: #6e7681; font: 11px ui-monospace,SFMono-Regular,Consolas,monospace; }}
</style>
<rect width="1000" height="540" rx="18" class="bg"/>
<rect x="24" y="24" width="952" height="492" rx="14" class="panel"/>
<text x="48" y="68" class="title">Context recall quality</text>
<text x="48" y="96" class="subtitle">Final injected context · required facts · precision · stale and workspace suppression</text>
<text x="48" y="128" class="section">Final context quality</text>
{''.join(rows)}
<text x="48" y="394" class="section">Ingestion integrity &amp; safety</text>
<rect x="48" y="410" width="205" height="70" rx="9" class="panel"/>
<text x="66" y="441" class="card-value">{accepted}</text>
<text x="66" y="462" class="card-label">Accepted documents</text>
<rect x="268" y="410" width="205" height="70" rx="9" class="panel"/>
<text x="286" y="441" class="card-value">{source_content_presence}</text>
<text x="286" y="462" class="card-label">Source content present</text>
<rect x="488" y="410" width="205" height="70" rx="9" class="panel"/>
<text x="506" y="441" class="card-value">{forbidden}</text>
<text x="506" y="462" class="card-label">Forbidden exposure</text>
<rect x="708" y="410" width="220" height="70" rx="9" class="panel"/>
<text x="726" y="441" class="card-value">{index_state}</text>
<text x="726" y="462" class="card-label">Index state · deleted {ingestion['deleted_documents']}</text>
<text x="48" y="502" class="footer">{html.escape(footer)}</text>
</svg>
'''


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render retrieval quality benchmark SVG")
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    result = json.loads(args.result.read_text(encoding="utf-8"))
    expected = render_svg(result)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"stale retrieval quality chart: {args.output}")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
