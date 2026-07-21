from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shlex
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wikibrain.config import BrainConfig
from wikibrain.curation import Curator
from wikibrain.hooks import process_hook
from wikibrain.recall import RecallService
from wikibrain.storage import BrainStore
from wikibrain.wikimap_adapter import WikimapAdapter


BENCHMARK_VERSION = "second-brain-v1"
CORPUS_VERSION = "second-brain-corpus-v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _normalized_file_bytes(path: Path) -> bytes:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(_normalized_file_bytes(path)).hexdigest()


def source_manifest_sha256() -> str:
    """Hash benchmark behavior and production sources, excluding result artifacts."""
    paths = [
        REPOSITORY_ROOT / "pyproject.toml",
        REPOSITORY_ROOT / "uv.lock",
        Path(__file__).resolve(),
        *sorted((REPOSITORY_ROOT / "src" / "wikibrain").glob("*.py")),
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(REPOSITORY_ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_normalized_file_bytes(path))
        digest.update(b"\0")
    return digest.hexdigest()


def _git_metadata() -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain=v1"],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return commit, dirty
    except (OSError, subprocess.CalledProcessError):
        return "unavailable", True


def _case(
    name: str,
    category: str,
    context: str,
    *,
    expected: tuple[str, ...] = (),
    forbidden: tuple[str, ...] = (),
) -> dict[str, Any]:
    missing = [value for value in expected if value not in context]
    leaked = [value for value in forbidden if value in context]
    return {
        "name": name,
        "category": category,
        "passed": not missing and not leaked,
        "expected": list(expected),
        "forbidden": list(forbidden),
        "missing": missing,
        "unexpected": leaked,
    }


def run_benchmark(
    *,
    root: Path,
    wikimap_command: str = "wikimap",
) -> dict[str, Any]:
    """Run a fixed-corpus, local-only second-brain regression benchmark."""

    atlas = root / "project-atlas"
    borealis = root / "project-borealis"
    atlas.mkdir(parents=True, exist_ok=True)
    borealis.mkdir(parents=True, exist_ok=True)

    config = BrainConfig.create(
        root / "brain",
        root / "brain" / "vault",
        [atlas, borealis],
    )
    config.wikimap_command = wikimap_command
    config.recall_result_limit = 8
    config.recall_char_limit = 12_000
    config.save()

    store = BrainStore(config.database_path)
    wikimap = WikimapAdapter(config.vault_path, wikimap_command, timeout=10.0)
    curator = Curator(config, store, wikimap)
    recall = RecallService(config, store, wikimap)

    evidence_id, _ = curator.remember(
        "Project Atlas contains uv.lock, and CI executes uv sync --frozen.",
        title="Atlas CI manifest observation",
        workspace=str(atlas),
        update_index=False,
        captured_at="2026-06-01T09:00:00+00:00",
    )
    old_decision_id, _ = curator.remember(
        "Package manager decision: use pip for Project Atlas commands.",
        title="Atlas package-manager decision",
        workspace=str(atlas),
        update_index=False,
        captured_at="2026-06-02T09:00:00+00:00",
    )
    current_decision_id, _ = curator.remember(
        "Package manager decision: use uv for Project Atlas commands. "
        "Project marker Atlas-204.",
        title="Atlas package-manager decision",
        workspace=str(atlas),
        update_index=False,
        captured_at="2026-07-01T09:00:00+00:00",
        relates_to=[evidence_id],
        supersedes=[old_decision_id],
    )
    curator.remember(
        "Mina owns the Project Atlas release checklist. Joon is the backup reviewer.",
        title="Atlas release ownership",
        workspace=str(atlas),
        update_index=False,
        captured_at="2026-07-02T09:00:00+00:00",
    )
    curator.remember(
        "I prefer concise Korean status reports with concrete next actions.",
        title="Status report preference",
        workspace=None,
        update_index=False,
        captured_at="2026-07-03T09:00:00+00:00",
    )
    curator.remember(
        "Project marker for Borealis private client is Cedar-991.",
        title="Borealis client context",
        workspace=str(borealis),
        update_index=False,
        captured_at="2026-07-04T09:00:00+00:00",
    )

    raw_secret = "benchmark-secret-value-12345"
    curator.remember(
        f"Rotation marker Saffron-418.\nAPI_KEY={raw_secret}",
        title="Atlas credential rotation",
        workspace=str(atlas),
        update_index=False,
        captured_at="2026-07-05T09:00:00+00:00",
    )
    curator.update_index()

    decision_context = recall.context(
        str(atlas), "package manager decision", include_recent=False
    )
    owner_context = recall.context(
        str(atlas), "who owns the release checklist", include_recent=False
    )
    isolation_context = recall.context(
        str(atlas), "project marker", include_recent=False
    )
    secret_context = recall.context(str(atlas), "Saffron-418", include_recent=False)
    secret_bytes = raw_secret.encode("utf-8")
    durable_storage_clean = all(
        secret_bytes not in path.read_bytes()
        for path in config.home_path.rglob("*")
        if path.is_file()
    )
    secret_context += (
        "\n<durable_storage_clean>"
        f"{str(durable_storage_clean).lower()}"
        "</durable_storage_clean>"
    )
    preference_context = recall.context(
        str(atlas), "status report preference", include_recent=False
    )

    process_hook(
        "claude",
        {
            "session_id": "benchmark-claude",
            "cwd": str(atlas),
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Record the release gate marker Nebula-42.",
        },
        config,
    )
    process_hook(
        "claude",
        {
            "session_id": "benchmark-claude",
            "cwd": str(atlas),
            "hook_event_name": "Stop",
            "last_assistant_message": (
                "Project Atlas release gate Nebula-42 requires two approvals."
            ),
        },
        config,
    )
    _, codex_start = process_hook(
        "codex",
        {
            "session_id": "benchmark-codex",
            "cwd": str(atlas),
            "hook_event_name": "SessionStart",
            "source": "startup",
        },
        config,
    )

    cases = [
        _case(
            "current-decision-recall",
            "temporal",
            decision_context,
            expected=("use uv", current_decision_id),
            forbidden=("use pip",),
        ),
        _case(
            "decision-evidence-link",
            "relations",
            decision_context,
            expected=(
                'type="relates-to"',
                f'document_id="{evidence_id}"',
                "uv sync --frozen",
                'type="supersedes"',
                f'document_id="{old_decision_id}"',
            ),
        ),
        _case(
            "person-project-context",
            "work-context",
            owner_context,
            expected=("Mina", "Project Atlas", "Joon"),
        ),
        _case(
            "source-provenance",
            "provenance",
            decision_context,
            expected=("<source path=", "<captured_at>", current_decision_id),
        ),
        _case(
            "workspace-isolation",
            "privacy",
            isolation_context,
            expected=("Atlas-204",),
            forbidden=("Cedar-991", "Borealis private client"),
        ),
        _case(
            "secret-redaction",
            "privacy",
            secret_context,
            expected=(
                "Saffron-418",
                "[REDACTED]",
                "<durable_storage_clean>true</durable_storage_clean>",
            ),
            forbidden=(raw_secret,),
        ),
        _case(
            "global-preference-recall",
            "scope",
            preference_context,
            expected=("concise Korean", "concrete next actions"),
        ),
        _case(
            "claude-to-codex-handoff",
            "handoff",
            codex_start.context,
            expected=("Nebula-42", 'provider="claude"'),
        ),
    ]

    required_atoms = sum(len(case["expected"]) for case in cases)
    missing_atoms = sum(len(case["missing"]) for case in cases)
    forbidden_atoms = sum(len(case["forbidden"]) for case in cases)
    leaked_atoms = sum(len(case["unexpected"]) for case in cases)
    clean_contexts = sum(1 for case in cases if not case["unexpected"])

    passed = sum(1 for case in cases if case["passed"])
    git_commit, git_dirty = _git_metadata()
    reproduction_command = shlex.join(
        [
            "uv",
            "run",
            "python",
            "-m",
            "benchmarks.second_brain",
            "--wikimap",
            Path(wikimap_command).name,
            "--format",
            "json",
            "--output",
            "benchmarks/results/second-brain-v1.json",
        ]
    )
    return {
        "benchmark": BENCHMARK_VERSION,
        "retrieval_mode": "final-context-contract",
        "retrieval_modes": {
            "query_checks": "query-only-no-recent-fallback",
            "handoff_check": "session-start-recent-context",
        },
        "engine": wikimap.version() or "unavailable",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "corpus_documents": store.document_count(),
        "checks_passed": passed,
        "checks_total": len(cases),
        "score_percent": round(100.0 * passed / len(cases), 1),
        "context_quality": {
            "required_atom_recall": (
                (required_atoms - missing_atoms) / required_atoms
                if required_atoms
                else 0.0
            ),
            "clean_context_rate": clean_contexts / len(cases) if cases else 0.0,
            "forbidden_atom_rate": (
                leaked_atoms / forbidden_atoms if forbidden_atoms else 0.0
            ),
            "required_atoms": required_atoms,
            "forbidden_atoms": forbidden_atoms,
        },
        "provenance": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "corpus_version": CORPUS_VERSION,
            "runner_sha256": _file_sha256(Path(__file__).resolve()),
            "source_manifest_sha256": source_manifest_sha256(),
            "git_commit": git_commit,
            "git_dirty": git_dirty,
            "reproduction_command": reproduction_command,
        },
        "cases": cases,
    }


def _markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# WikiBrain benchmark: {result['benchmark']}",
        "",
        f"- Score: **{result['checks_passed']}/{result['checks_total']} "
        f"({result['score_percent']}%)**",
        f"- Corpus documents: **{result['corpus_documents']}**",
        f"- Required context atoms recalled: "
        f"**{100.0 * result['context_quality']['required_atom_recall']:.2f}%**",
        f"- Clean contexts: "
        f"**{100.0 * result['context_quality']['clean_context_rate']:.2f}%**",
        f"- Forbidden atom rate: "
        f"**{100.0 * result['context_quality']['forbidden_atom_rate']:.2f}%**",
        f"- Engine: `{result['engine']}`",
        "",
        "| Check | Category | Result |",
        "|---|---|---|",
    ]
    for case in result["cases"]:
        mark = "PASS" if case["passed"] else "FAIL"
        lines.append(f"| `{case['name']}` | {case['category']} | {mark} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wikimap", default=shutil.which("wikimap") or "wikimap")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="wikibrain-benchmark-") as temporary:
        result = run_benchmark(
            root=Path(temporary),
            wikimap_command=args.wikimap,
        )
    text = (
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.format == "json"
        else _markdown(result)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if result["checks_passed"] == result["checks_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
