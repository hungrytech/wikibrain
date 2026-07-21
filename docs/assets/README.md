# Visual assets

`wikibrain-mascot.svg` is an original, hand-authored SVG illustration created
for WikiBrain. It does not incorporate third-party logos, characters, or stock
art.

The illustration is distributed under the repository's [MIT License](../../LICENSE).

`benchmark-second-brain-v1.svg` is generated from the committed machine-readable
benchmark result. Regenerate and verify it with:

Run these commands from the repository root:

```bash
uv run --locked python scripts/render_benchmark_chart.py
uv run --locked python scripts/render_benchmark_chart.py --check
```
