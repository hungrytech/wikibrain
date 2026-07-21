from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import subprocess
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wikibrain.config import BrainConfig
from wikibrain.curation import Curator
from wikibrain.recall import RecallService
from wikibrain.storage import BrainStore
from wikibrain.wikimap_adapter import WikimapAdapter


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _dcg(document_ids: Sequence[str], relevance: Mapping[str, int], cutoff: int) -> float:
    return sum(
        ((2 ** relevance.get(document_id, 0)) - 1) / math.log2(rank + 1)
        for rank, document_id in enumerate(document_ids[:cutoff], start=1)
    )


def score_rankings(
    cases: Iterable[Mapping[str, Any]], *, cutoffs: tuple[int, ...] = (1, 3, 5)
) -> dict[str, Any]:
    """Score ranked document IDs against per-query relevance and safety labels."""
    normalized_cutoffs = tuple(sorted(set(cutoffs)))
    if not normalized_cutoffs or normalized_cutoffs[0] < 1:
        raise ValueError("cutoffs must contain positive integers")

    case_list = list(cases)
    recalls: dict[int, list[float]] = {cutoff: [] for cutoff in normalized_cutoffs}
    reciprocal_ranks: list[float] = []
    ndcgs: dict[int, list[float]] = {cutoff: [] for cutoff in normalized_cutoffs}
    top1_matches: list[float] = []
    forbidden_queries: list[float] = []
    violations: Counter[str] = Counter()

    for case in case_list:
        relevance = {str(key): int(value) for key, value in case["relevant"].items()}
        retrieved = list(
            dict.fromkeys(str(document_id) for document_id in case["retrieved"])
        )
        forbidden = {str(key): str(value) for key, value in case["forbidden"].items()}
        relevant_ids = set(relevance)

        for cutoff in normalized_cutoffs:
            found = relevant_ids.intersection(retrieved[:cutoff])
            recalls[cutoff].append(len(found) / len(relevant_ids) if relevant_ids else 0.0)
            ideal = sorted(relevance, key=lambda document_id: relevance[document_id], reverse=True)
            ideal_dcg = _dcg(ideal, relevance, cutoff)
            ndcgs[cutoff].append(
                _dcg(retrieved, relevance, cutoff) / ideal_dcg if ideal_dcg else 0.0
            )

        first_rank = next(
            (rank for rank, document_id in enumerate(retrieved, start=1) if document_id in relevant_ids),
            None,
        )
        reciprocal_ranks.append(1.0 / first_rank if first_rank else 0.0)
        top1_matches.append(float(bool(retrieved and retrieved[0] in relevant_ids)))

        exposed = {document_id for document_id in retrieved if document_id in forbidden}
        forbidden_queries.append(float(bool(exposed)))
        violations.update(forbidden[document_id] for document_id in exposed)

    metrics: dict[str, Any] = {"query_count": len(case_list)}
    for cutoff in normalized_cutoffs:
        metrics[f"recall_at_{cutoff}"] = _mean(recalls[cutoff])
        metrics[f"ndcg_at_{cutoff}"] = _mean(ndcgs[cutoff])
    metrics.update(
        {
            "mrr": _mean(reciprocal_ranks),
            "top1_source_match": _mean(top1_matches),
            "forbidden_query_rate": _mean(forbidden_queries),
            "violations": dict(sorted(violations.items())),
        }
    )
    return metrics


def score_contexts(cases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Score records and labeled facts present in the final rendered context."""
    case_list = list(cases)
    recalls: list[float] = []
    precisions: list[float] = []
    f1_scores: list[float] = []
    required_atom_count = 0
    found_atom_count = 0
    forbidden_queries: list[float] = []
    violations: Counter[str] = Counter()

    for case in case_list:
        relevant = {str(document_id) for document_id in case["relevant"]}
        records = list(dict.fromkeys(str(document_id) for document_id in case["records"]))
        found = relevant.intersection(records)
        recall = len(found) / len(relevant) if relevant else 0.0
        precision = len(found) / len(records) if records else 0.0
        f1 = (
            2.0 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        recalls.append(recall)
        precisions.append(precision)
        f1_scores.append(f1)

        context = str(case["context"]).casefold()
        required_atoms = [str(atom).casefold() for atom in case["required_atoms"]]
        required_atom_count += len(required_atoms)
        found_atom_count += sum(atom in context for atom in required_atoms)

        forbidden = {
            str(document_id): str(reason)
            for document_id, reason in case["forbidden"].items()
        }
        exposed = {document_id for document_id in records if document_id in forbidden}
        forbidden_queries.append(float(bool(exposed)))
        violations.update(forbidden[document_id] for document_id in exposed)

    return {
        "query_count": len(case_list),
        "context_recall": _mean(recalls),
        "context_precision": _mean(precisions),
        "context_f1": _mean(f1_scores),
        "required_atom_recall": (
            found_atom_count / required_atom_count if required_atom_count else 0.0
        ),
        "forbidden_query_rate": _mean(forbidden_queries),
        "violations": dict(sorted(violations.items())),
    }


def derive_forbidden(
    corpus: Mapping[str, Any], query: Mapping[str, Any]
) -> dict[str, str]:
    query_workspace = str(query["workspace"])
    superseded_ids = {
        str(superseded_id)
        for document in corpus["documents"]
        for superseded_id in document.get("supersedes", [])
    }
    forbidden: dict[str, str] = {}
    for document in corpus["documents"]:
        document_id = str(document["id"])
        workspace_value = document.get("workspace")
        workspace = "global" if workspace_value is None else str(workspace_value)
        if document.get("delete_after_ingest"):
            forbidden[document_id] = "deleted"
        elif document_id in superseded_ids:
            forbidden[document_id] = "superseded"
        elif workspace not in {query_workspace, "global"}:
            forbidden[document_id] = "workspace"
    forbidden.update(
        {str(key): str(value) for key, value in query.get("forbidden", {}).items()}
    )
    return forbidden


def validate_corpus(corpus: Mapping[str, Any]) -> None:
    if not corpus.get("corpus_version"):
        raise ValueError("corpus_version is required")

    documents = list(corpus.get("documents", []))
    document_ids = [str(document.get("id", "")) for document in documents]
    if any(not document_id for document_id in document_ids):
        raise ValueError("every document requires a non-empty id")
    duplicate_documents = sorted(
        document_id for document_id, count in Counter(document_ids).items() if count > 1
    )
    if duplicate_documents:
        raise ValueError(f"duplicate document id: {duplicate_documents[0]}")

    seen_documents: set[str] = set()
    for document in documents:
        document_id = str(document["id"])
        supersedes = document.get("supersedes", [])
        if not isinstance(supersedes, list):
            raise ValueError(f"document {document_id} supersedes must be a list")
        for superseded_id in supersedes:
            if str(superseded_id) not in seen_documents:
                raise ValueError(
                    f"document {document_id} supersedes unknown or later document id: "
                    f"{superseded_id}"
                )
        seen_documents.add(document_id)

    queries = list(corpus.get("queries", []))
    query_ids = [str(query.get("id", "")) for query in queries]
    if any(not query_id for query_id in query_ids):
        raise ValueError("every query requires a non-empty id")
    duplicate_queries = sorted(
        query_id for query_id, count in Counter(query_ids).items() if count > 1
    )
    if duplicate_queries:
        raise ValueError(f"duplicate query id: {duplicate_queries[0]}")

    known = set(document_ids)
    for query in queries:
        query_id = str(query["id"])
        relevant = {str(key) for key in query.get("relevant", {})}
        forbidden = {str(key) for key in query.get("forbidden", {})}
        required_context = query.get("required_context")
        if (
            not isinstance(required_context, list)
            or not required_context
            or any(not isinstance(atom, str) or not atom.strip() for atom in required_context)
        ):
            raise ValueError(
                f"query {query_id} required_context must be a non-empty list "
                "of non-empty strings"
            )
        if not relevant:
            raise ValueError(f"query {query_id} requires at least one relevant document")
        unknown = sorted((relevant | forbidden) - known)
        if unknown:
            raise ValueError(f"query {query_id} references unknown document id: {unknown[0]}")
        derived_forbidden = set(derive_forbidden(corpus, query))
        overlap = sorted(relevant & derived_forbidden)
        if overlap:
            raise ValueError(
                f"query {query_id} marks {overlap[0]} as both relevant and forbidden"
            )
        for document_id, grade in query.get("relevant", {}).items():
            if not isinstance(grade, int) or isinstance(grade, bool) or grade <= 0:
                raise ValueError(
                    f"query {query_id} has invalid relevance grade for {document_id}"
                )


def run_quality_benchmark(
    *,
    root: Path,
    corpus: Mapping[str, Any],
    wikimap_command: str = "wikimap",
) -> dict[str, Any]:
    """Ingest a labeled corpus and score production retrieval without content logs."""
    validate_corpus(corpus)
    workspace_names = {
        str(document["workspace"])
        for document in corpus["documents"]
        if document.get("workspace")
    }
    workspace_names.update(
        str(query["workspace"])
        for query in corpus["queries"]
        if query.get("workspace")
    )
    workspaces = {name: root / f"workspace-{name}" for name in workspace_names}
    for path in workspaces.values():
        path.mkdir(parents=True, exist_ok=True)

    config = BrainConfig.create(
        root / "brain",
        root / "brain" / "vault",
        list(workspaces.values()),
    )
    config.wikimap_command = wikimap_command
    config.recall_result_limit = max(5, len(corpus["documents"]))
    config.save()

    store = BrainStore(config.database_path)
    wikimap = WikimapAdapter(config.vault_path, wikimap_command, timeout=10.0)
    curator = Curator(config, store, wikimap)
    recall = RecallService(config, store, wikimap)

    symbolic_to_actual: dict[str, str] = {}
    actual_to_symbolic: dict[str, str] = {}
    source_content_matches = 0
    for document in corpus["documents"]:
        symbolic_id = str(document["id"])
        workspace_name = document.get("workspace")
        workspace = str(workspaces[str(workspace_name)]) if workspace_name else None
        supersedes = [
            symbolic_to_actual[str(target)]
            for target in document.get("supersedes", [])
        ]
        document_id, _ = curator.remember(
            str(document["text"]),
            title=str(document["title"]),
            workspace=workspace,
            update_index=False,
            captured_at=str(document["captured_at"]),
            supersedes=supersedes,
        )
        symbolic_to_actual[symbolic_id] = document_id
        actual_to_symbolic[document_id] = symbolic_id
        stored_row = store.document(document_id)
        expected_stored = str(document.get("expected_stored", document["text"]))
        if (
            stored_row is not None
            and expected_stored in Path(str(stored_row["path"])).read_text(encoding="utf-8")
        ):
            source_content_matches += 1

    curator.update_index()

    deleted_documents = 0
    for document in corpus["documents"]:
        if not document.get("delete_after_ingest"):
            continue
        document_id = symbolic_to_actual[str(document["id"])]
        row = store.document(document_id)
        if row is not None:
            Path(str(row["path"])).unlink(missing_ok=True)
        store.forget_document(document_id, "retrieval quality benchmark deletion")
        deleted_documents += 1
    if deleted_documents:
        curator.update_index()

    score_cases: list[dict[str, Any]] = []
    context_score_cases: list[dict[str, Any]] = []
    query_results: list[dict[str, Any]] = []
    engine_counts: Counter[str] = Counter()
    for query in corpus["queries"]:
        workspace_name = str(query["workspace"])
        hits, engine = recall.search(str(query["text"]), str(workspaces[workspace_name]))
        engine_counts[engine] += 1
        retrieved = [
            actual_to_symbolic[str(row["document_id"])]
            for _, row in hits
            if str(row["document_id"]) in actual_to_symbolic
        ]
        context = recall.context(
            str(workspaces[workspace_name]),
            str(query["text"]),
            include_recent=False,
        )
        context_records = list(
            dict.fromkeys(
                actual_to_symbolic[actual_id]
                for actual_id in re.findall(
                    r'<record index="\d+" id="([^"]+)"', context
                )
                if actual_id in actual_to_symbolic
            )
        )
        forbidden = derive_forbidden(corpus, query)
        context_score_cases.append(
            {
                "query_id": str(query["id"]),
                "relevant": query["relevant"],
                "records": context_records,
                "required_atoms": query.get("required_context", []),
                "context": context,
                "forbidden": forbidden,
            }
        )
        score_cases.append(
            {
                "query_id": str(query["id"]),
                "relevant": query["relevant"],
                "retrieved": retrieved,
                "forbidden": forbidden,
            }
        )
        query_results.append(
            {
                "query_id": str(query["id"]),
                "engine": engine,
                "context_records": context_records,
                "retrieved": [
                    {"rank": rank, "document_id": document_id}
                    for rank, document_id in enumerate(retrieved, start=1)
                ],
            }
        )

    return {
        "benchmark_version": "retrieval-quality-v1",
        "corpus_version": str(corpus["corpus_version"]),
        "ingestion": {
            "requested_documents": len(corpus["documents"]),
            "accepted_documents": len(symbolic_to_actual),
            "acceptance_rate": (
                len(symbolic_to_actual) / len(corpus["documents"])
                if corpus["documents"]
                else 0.0
            ),
            "source_content_presence_rate": (
                source_content_matches / len(corpus["documents"])
                if corpus["documents"]
                else 0.0
            ),
            "registered_documents": store.document_count(),
            "deleted_documents": deleted_documents,
            "index_clean": not store.index_dirty(),
        },
        "quality": score_rankings(score_cases),
        "context_quality": score_contexts(context_score_cases),
        "query_engines": dict(sorted(engine_counts.items())),
        "queries": query_results,
        "wikimap_version": wikimap.version(),
    }


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _normalized_bytes(path: Path) -> bytes:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(_normalized_bytes(path)).hexdigest()


def _source_manifest_sha256(corpus_path: Path) -> str:
    paths = [
        REPOSITORY_ROOT / "pyproject.toml",
        REPOSITORY_ROOT / "uv.lock",
        Path(__file__).resolve(),
        corpus_path.resolve(),
        *sorted((REPOSITORY_ROOT / "src" / "wikibrain").glob("*.py")),
    ]
    digest = hashlib.sha256()
    for path in paths:
        label = (
            path.relative_to(REPOSITORY_ROOT).as_posix()
            if path.is_relative_to(REPOSITORY_ROOT)
            else path.name
        )
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_normalized_bytes(path))
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark WikiBrain retrieval quality")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wikimap-command", default="wikimap")
    args = parser.parse_args(argv)

    corpus_path = args.corpus.resolve()
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    commit, dirty = _git_metadata()
    with tempfile.TemporaryDirectory(prefix="wikibrain-retrieval-quality-") as directory:
        result = run_quality_benchmark(
            root=Path(directory),
            corpus=corpus,
            wikimap_command=args.wikimap_command,
        )

    result["generated_at"] = datetime.now(UTC).isoformat()
    result["environment"] = {
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    result["provenance"] = {
        "corpus_sha256": _sha256(corpus_path),
        "source_manifest_sha256": _source_manifest_sha256(corpus_path),
        "git_commit": commit,
        "git_dirty": dirty,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
