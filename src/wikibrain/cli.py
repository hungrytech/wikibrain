from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import __version__
from .config import CONFIG_VERSION, BrainConfig, default_home, default_workspace
from .curation import Curator
from .hooks import run_hook_command
from .installer import (
    configured_hook_status,
    hook_status,
    install_hooks,
    uninstall_hooks,
)
from .recall import RecallService
from .skill_installer import (
    default_skill_targets,
    install_skills,
    skill_status,
    uninstall_skills,
)
from .storage import BrainStore, stable_hash
from .wikimap_adapter import WikimapAdapter, WikimapError


def _clients(value: str) -> list[str]:
    parsed = list(
        dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip())
    )
    if not parsed:
        raise argparse.ArgumentTypeError("at least one client is required")
    invalid = sorted(set(parsed) - {"claude", "codex", "grok"})
    if invalid:
        raise argparse.ArgumentTypeError(
            f"unknown client(s): {', '.join(invalid)}"
        )
    return parsed


def _emit(payload: Any, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif isinstance(payload, str):
        print(payload)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                detail = ", ".join(f"{key}={value}" for key, value in item.items())
                print(detail)
            else:
                print(item)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            print(f"{key}: {value}")


def _load(home: Path) -> BrainConfig:
    try:
        return BrainConfig.load(home)
    except FileNotFoundError as error:
        raise RuntimeError(
            f"WikiBrain is not initialized at {home}. Run `brainctl init` first."
        ) from error


def _path_overrides(args: argparse.Namespace) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    if getattr(args, "claude_settings", None):
        paths["claude"] = Path(args.claude_settings).expanduser()
    if getattr(args, "codex_hooks", None):
        paths["codex"] = Path(args.codex_hooks).expanduser()
    if getattr(args, "grok_hooks", None):
        paths["grok"] = Path(args.grok_hooks).expanduser()
    return paths


def _skill_targets(args: argparse.Namespace, clients: list[str]) -> dict[str, Path]:
    targets = default_skill_targets(clients)
    if getattr(args, "claude_skill_dir", None) and "claude" in clients:
        targets["claude"] = Path(args.claude_skill_dir).expanduser()
    if getattr(args, "agents_skill_dir", None) and "codex" in clients:
        targets["agents"] = Path(args.agents_skill_dir).expanduser()
    if getattr(args, "grok_skill_dir", None) and "grok" in clients:
        targets["grok"] = Path(args.grok_skill_dir).expanduser()
    return targets


def _client_readiness(
    clients: list[str],
    *,
    applied: bool,
    hooks_installed: bool,
    skills_installed: bool,
) -> dict[str, str]:
    if not applied:
        readiness = {"manual_commands": "not-installed-dry-run"}
        if "claude" in clients:
            readiness["claude_automatic_hooks"] = "preview-only"
        if "codex" in clients:
            readiness["codex_manual_skill"] = "preview-only"
            readiness["codex_automatic_hooks"] = "preview-only"
            readiness["codex_trust_owner"] = (
                "Codex; brainctl does not grant, bypass, or inspect hook trust"
            )
        if "grok" in clients:
            readiness["grok_manual_skill"] = "preview-only"
            readiness["grok_automatic_capture"] = "preview-only"
            readiness["grok_automatic_recall"] = (
                "unsupported-by-passive-hook-stdout-contract"
            )
        return readiness

    readiness = {"manual_commands": "ready"}
    if "claude" in clients:
        readiness["claude_automatic_hooks"] = (
            "ready-after-new-session" if hooks_installed else "not-installed"
        )
    if "codex" in clients:
        readiness["codex_manual_skill"] = (
            "installed-for-new-session" if skills_installed else "not-installed"
        )
        readiness["codex_automatic_hooks"] = (
            "codex-review-required-unless-already-trusted"
            if hooks_installed
            else "not-installed"
        )
        readiness["codex_trust_owner"] = (
            "Codex; brainctl does not grant, bypass, or inspect hook trust"
        )
    if "grok" in clients:
        readiness["grok_manual_skill"] = (
            "installed-for-new-session" if skills_installed else "not-installed"
        )
        readiness["grok_automatic_capture"] = (
            "ready-after-new-session" if hooks_installed else "not-installed"
        )
        readiness["grok_automatic_recall"] = (
            "manual-skill-required-passive-hook-stdout-is-ignored"
        )
    return readiness


def _next_step(
    clients: list[str],
    *,
    applied: bool,
    hooks_installed: bool,
) -> str:
    if not applied:
        return (
            "Dry run complete; no files were changed. Run brainctl init "
            "without --dry-run to apply this setup."
        )
    if not hooks_installed:
        return (
            "Manual mode is ready: use brainctl remember/recall. "
            "Automatic lifecycle capture and recall are disabled because "
            "hooks were not installed."
        )
    steps = ["Start a new agent session."]
    if "claude" in clients:
        steps.append("Claude user hooks are ready.")
    if "codex" in clients:
        steps.append(
            "Codex manual commands are ready now and its installed skill loads "
            "in the new session; for automatic hooks, open /hooks and "
            "review/trust the current definitions."
        )
    if "grok" in clients:
        steps.append(
            "Grok capture hooks and skill are ready; Grok ignores passive-hook "
            "stdout, so use the WikiBrain skill or brainctl recall for recalled context."
        )
    return " ".join(steps)


def command_init(args: argparse.Namespace, home: Path) -> int:
    if (home / "config.json").exists() and not args.force:
        config = BrainConfig.load(home)
        created = False
    else:
        workspaces = (
            [Path(value) for value in args.workspace]
            if args.workspace
            else [default_workspace()]
        )
        if args.dry_run:
            selected_home = home.expanduser().resolve()
            selected_vault = (
                Path(args.vault).expanduser().resolve()
                if args.vault
                else selected_home / "vault"
            )
            config = BrainConfig(
                version=CONFIG_VERSION,
                home=str(selected_home),
                vault=str(selected_vault),
                workspace_roots=[
                    str(path.expanduser().resolve()) for path in workspaces
                ],
            )
        else:
            config = BrainConfig.create(
                home,
                Path(args.vault) if args.vault else None,
                workspaces,
            )
        created = True
    indexed = False
    if not args.dry_run:
        store = BrainStore(config.database_path)
        wikimap = WikimapAdapter(config.vault_path, config.wikimap_command)
        if wikimap.available:
            generation = store.index_generation()
            try:
                wikimap.update()
                indexed = store.mark_index_clean(generation)
            except WikimapError:
                indexed = False
    hooks: list[dict[str, Any]] = []
    if not args.no_hooks:
        hooks = install_hooks(
            config,
            args.clients,
            command=args.command,
            paths=_path_overrides(args),
            dry_run=args.dry_run,
        )
    skills: list[dict[str, Any]] = []
    if not args.no_skills:
        skills = install_skills(
            args.clients,
            targets=_skill_targets(args, args.clients),
            dry_run=args.dry_run,
        )
    _emit(
        {
            "status": "ok",
            "created": created,
            "dry_run": args.dry_run,
            "home": str(config.home_path),
            "vault": str(config.vault_path),
            "workspace_roots": config.workspace_roots,
            "wikimap_indexed": indexed,
            "hooks": hooks,
            "skills": skills,
            "client_readiness": _client_readiness(
                args.clients,
                applied=not args.dry_run,
                hooks_installed=not args.no_hooks,
                skills_installed=not args.no_skills,
            ),
            "next": _next_step(
                args.clients,
                applied=not args.dry_run,
                hooks_installed=not args.no_hooks,
            ),
        },
        args.json,
    )
    return 0


def command_setup(args: argparse.Namespace, home: Path) -> int:
    config = _load(home)
    results = install_hooks(
        config,
        args.clients,
        command=args.command,
        paths=_path_overrides(args),
        dry_run=args.dry_run,
    )
    skills: list[dict[str, Any]] = []
    if not args.no_skills:
        skills = install_skills(
            args.clients,
            targets=_skill_targets(args, args.clients),
            dry_run=args.dry_run,
        )
    _emit({"hooks": results, "skills": skills}, args.json)
    if "codex" in args.clients and not args.json:
        print("Codex: start a new session, open /hooks, then trust the reviewed definitions.")
    return 0


def command_hooks(args: argparse.Namespace, home: Path) -> int:
    paths = _path_overrides(args)
    if args.hooks_command == "status":
        _emit(hook_status(paths, clients=args.clients), args.json)
        return 0
    config = _load(home)
    results = uninstall_hooks(
        config,
        args.clients,
        paths=paths,
        dry_run=args.dry_run,
    )
    _emit(results, args.json)
    return 0


def command_skills(args: argparse.Namespace) -> int:
    targets = _skill_targets(args, args.clients)
    if args.skills_command == "status":
        _emit(skill_status(args.clients, targets=targets), args.json)
        return 0
    _emit(
        uninstall_skills(
            args.clients,
            targets=targets,
            dry_run=args.dry_run,
        ),
        args.json,
    )
    return 0


def command_remember(args: argparse.Namespace, home: Path) -> int:
    config = _load(home)
    text = args.text
    if text is None:
        text = sys.stdin.read()
    if not text.strip():
        raise RuntimeError("memory text is empty")
    store = BrainStore(config.database_path)
    wikimap = WikimapAdapter(config.vault_path, config.wikimap_command)
    curator = Curator(config, store, wikimap)
    if getattr(args, "global_memory", False):
        workspace = None
    else:
        requested = str(Path(args.workspace or Path.cwd()).expanduser().resolve())
        scope = config.scope_for(requested)
        if scope is None:
            raise RuntimeError(
                "memory workspace is outside the allowlist; use --global only "
                "when cross-project recall is intentional"
            )
        workspace = str(scope)
    document_id, path = curator.remember(
        text,
        title=args.title,
        workspace=workspace,
        source="brainctl",
        relates_to=args.relates_to,
        supersedes=args.supersedes,
    )
    _emit(
        {
            "status": "ok",
            "id": document_id,
            "path": str(path),
            "relations": {
                "relates_to": args.relates_to,
                "supersedes": args.supersedes,
            },
        },
        args.json,
    )
    return 0


def command_recall(args: argparse.Namespace, home: Path) -> int:
    config = _load(home)
    cwd = str(Path(args.workspace or Path.cwd()).expanduser().resolve())
    scope = config.scope_for(cwd)
    if config.paused or scope is None:
        _emit({"status": "skipped", "reason": "workspace-not-allowed"}, args.json)
        return 0
    store = BrainStore(config.database_path)
    wikimap = WikimapAdapter(config.vault_path, config.wikimap_command)
    context = RecallService(config, store, wikimap).context(str(scope), args.query)
    _emit({"status": "ok", "context": context} if args.json else context, args.json)
    return 0


def command_pause(args: argparse.Namespace, home: Path, paused: bool) -> int:
    config = _load(home)
    config.paused = paused
    config.save()
    _emit({"status": "paused" if paused else "active"}, args.json)
    return 0


def command_status(args: argparse.Namespace, home: Path) -> int:
    try:
        config = BrainConfig.load(home)
    except FileNotFoundError:
        _emit({"status": "not-initialized", "home": str(home)}, args.json)
        return 1
    store = BrainStore(config.database_path)
    wikimap = WikimapAdapter(config.vault_path, config.wikimap_command)
    _emit(
        {
            "status": "paused" if config.paused else "active",
            "home": str(config.home_path),
            "vault": str(config.vault_path),
            "workspace_roots": config.workspace_roots,
            "wikimap": wikimap.version(),
            "index_dirty": store.index_dirty(),
            "pending_archives": {
                "turns": len(store.pending_completed_turns()),
                "handoffs": len(store.pending_handoffs()),
                "promotions": len(store.pending_promotions()),
            },
            "counts": store.counts(),
            "hooks": configured_hook_status(config),
            "skills": skill_status(["claude", "codex", "grok"]),
            "archive_security": (
                "redacted plaintext, mode 0600; filesystem encryption is recommended"
            ),
        },
        args.json,
    )
    return 0


def command_reindex(args: argparse.Namespace, home: Path) -> int:
    config = _load(home)
    store = BrainStore(config.database_path)
    updated = Curator(
        config,
        store,
        WikimapAdapter(config.vault_path, config.wikimap_command),
    ).update_index()
    _emit(
        {
            "status": "ok" if updated else "degraded",
            "index_updated": updated,
            "index_dirty": store.index_dirty(),
        },
        args.json,
    )
    return 0 if updated else 1


def _offline_self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="wikibrain-doctor-") as temporary:
        root = Path(temporary)
        config = BrainConfig.create(root, root / "vault", [root])
        store = BrainStore(config.database_path)
        with store.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return {
            "config_write": True,
            "sqlite": True,
            "file_permissions": oct(config.config_path.stat().st_mode & 0o777),
        }


def command_doctor(args: argparse.Namespace, home: Path) -> int:
    checks: dict[str, Any] = {"self_test": _offline_self_test()}
    healthy = True
    if (home / "config.json").exists():
        config = BrainConfig.load(home)
        store = BrainStore(config.database_path)
        try:
            with store.connect() as connection:
                integrity = connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
            if str(integrity).lower() != "ok":
                healthy = False
        except sqlite3.Error as error:
            integrity = str(error)
            healthy = False
        index_dirty = store.index_dirty()
        if index_dirty:
            healthy = False
        pending_archives = {
            "turns": len(store.pending_completed_turns()),
            "handoffs": len(store.pending_handoffs()),
            "promotions": len(store.pending_promotions()),
        }
        if any(pending_archives.values()):
            healthy = False
        checks.update(
            {
                "initialized": True,
                "database_integrity": integrity,
                "counts": store.counts(),
                "index_dirty": index_dirty,
                "pending_archives": pending_archives,
                "home_mode": oct(config.home_path.stat().st_mode & 0o777),
                "config_mode": oct(config.config_path.stat().st_mode & 0o777),
            }
        )
        if index_dirty:
            checks["index_action"] = "Run `brainctl reindex`."
        if not args.offline:
            wikimap = WikimapAdapter(config.vault_path, config.wikimap_command)
            checks["wikimap"] = wikimap.version()
            if not wikimap.available:
                healthy = False
                checks["wikimap_action"] = "Install wikimap or use the Homebrew package."
            elif checks["wikimap"] is None:
                healthy = False
                checks["wikimap_action"] = "The configured Wikimap command is broken."
            else:
                try:
                    checks["wikimap_doctor"] = wikimap.doctor()
                except WikimapError as error:
                    healthy = False
                    checks["wikimap_doctor"] = str(error)
                    checks["wikimap_action"] = "Run `wikimap update`, then retry."
        if not args.skip_hooks:
            checks["hooks"] = configured_hook_status(config)
            invalid_hooks = [
                status["client"]
                for status in checks["hooks"]
                if not status.get("valid")
            ]
            if invalid_hooks:
                healthy = False
                checks["hooks_action"] = (
                    "Run `brainctl setup`, then review Codex definitions with /hooks."
                )
        else:
            checks["hooks"] = "skipped"
        if any(pending_archives.values()):
            checks["archive_action"] = (
                "After fixing vault write permissions, trigger any new allowed "
                "agent hook to drain the durable outbox."
            )
        if (
            isinstance(checks.get("hooks"), list)
            and any(
                status.get("client") == "codex"
                for status in checks["hooks"]
            )
        ):
            checks["codex_hook_trust"] = "codex-owned-not-inspected"
            checks["codex_action"] = (
                "brainctl doctor verifies the installed definitions but Codex "
                "owns their trust state; WikiBrain does not inspect or change "
                "it. If the current definition hash has not been trusted, "
                "open /hooks and review/trust it."
            )
    else:
        healthy = False
        checks["initialized"] = False
        checks["next"] = "Run `brainctl init`."
    checks["status"] = "ok" if healthy else "degraded"
    _emit(checks, args.json)
    return 0 if healthy else 1


def _erase_owned_paths(config: BrainConfig, values: list[str]) -> None:
    vault = config.vault_path.resolve()
    paths: list[Path] = []
    for value in values:
        path = Path(value)
        try:
            path.resolve().relative_to(vault)
        except (OSError, RuntimeError, ValueError) as error:
            raise RuntimeError(
                f"refusing to erase a path outside the owned vault: {path}"
            ) from error
        paths.append(path)
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise RuntimeError(f"could not erase owned memory file: {path}") from error
        parent = path.parent
        while parent != vault:
            try:
                parent.rmdir()
            except FileNotFoundError:
                pass
            except OSError:
                break
            parent = parent.parent


def _prune_forget_receipts(directory: Path, keep: int = 100) -> None:
    receipts = sorted(
        directory.glob("forget-*.json"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    for expired in receipts[:-keep]:
        expired.unlink(missing_ok=True)


def _drain_relation_cleanup_outbox(curator: Curator, store: BrainStore) -> int:
    completed = 0
    while True:
        pending = store.pending_relation_cleanups()
        if not pending:
            return completed
        for cleanup in pending:
            source_path = str(cleanup["source_path"])
            target_document_id = str(cleanup["target_document_id"])
            curator.remove_relation_target(Path(source_path), target_document_id)
            store.complete_relation_cleanup(source_path, target_document_id)
            completed += 1


def command_forget(args: argparse.Namespace, home: Path) -> int:
    config = _load(home)
    store = BrainStore(config.database_path)
    cascade_session: str | None = None
    cascade_provider: str | None = None
    selected_provider: str | None = getattr(args, "provider", None)
    if args.document:
        row = store.document(args.document)
        lineage: dict[str, Any] | None = None
        if row is not None:
            lineage = {
                "provider": row["provider"],
                "session_id": row["session_id"],
            }
        elif getattr(args, "cascade", False):
            lineage = store.tombstone_receipt(f"document:{args.document}")
        if getattr(args, "cascade", False) and lineage and lineage.get("session_id"):
            cascade_session = str(lineage["session_id"])
            if lineage.get("provider"):
                cascade_provider = str(lineage["provider"])
            if not cascade_provider:
                raise ValueError(
                    "source provider is unavailable; cascade cannot be scoped safely"
                )
            rows = store.documents_for_session(cascade_session, cascade_provider)
            preview = {
                "selector": f"session:{cascade_provider}:{cascade_session}",
                "requested_document": args.document,
                "cascade": True,
                "warning": "all evidence and memories from this source session",
                "paths": [str(value["path"]) for value in rows],
            }
        elif getattr(args, "cascade", False):
            raise ValueError(
                "document has no source session lineage; refusing a partial cascade"
            )
        else:
            adaptive_rows = store.adaptive_documents_for_source(args.document)
            preview = {
                "selector": f"document:{args.document}",
                "cascade": False,
                "paths": [
                    *([str(row["path"])] if row else []),
                    *(str(value["path"]) for value in adaptive_rows),
                ],
                "derived_adaptive_memories": [
                    str(value["document_id"]) for value in adaptive_rows
                ],
            }
    else:
        if selected_provider is None:
            providers = store.providers_for_session(args.session)
            if len(providers) != 1:
                detail = (
                    "specify --provider because no unique provider could be inferred"
                    if not providers
                    else "specify --provider; this session ID exists for: "
                    + ", ".join(providers)
                )
                raise ValueError(detail)
            selected_provider = providers[0]
        rows = store.documents_for_session(args.session, selected_provider)
        preview = {
            "selector": f"session:{selected_provider}:{args.session}",
            "cascade": True,
            "paths": [str(row["path"]) for row in rows],
        }
    if not args.apply:
        preview["dry_run"] = True
        _emit(preview, args.json)
        return 0

    store.mark_index_dirty()
    _erase_owned_paths(config, preview["paths"])
    receipt = (
        store.forget_session(
            cascade_session,
            args.reason,
            provider=cascade_provider,
        )
        if cascade_session
        else store.forget_document(args.document, args.reason)
        if args.document
        else store.forget_session(
            args.session,
            args.reason,
            provider=selected_provider,
        )
    )
    # A hook may finish between preview and the SQLite tombstone transaction.
    # Replaying the receipt also makes a partially failed erase recoverable.
    _erase_owned_paths(config, [str(value) for value in receipt.get("paths", [])])
    curator = Curator(
        config,
        store,
        WikimapAdapter(config.vault_path, config.wikimap_command),
    )
    relation_cleanups = _drain_relation_cleanup_outbox(curator, store)
    store.checkpoint()
    index_updated = curator.update_index()
    receipt["index_updated"] = index_updated
    receipt["relation_cleanups"] = relation_cleanups
    receipt_path = (
        config.home_path
        / "receipts"
        / f"forget-{stable_hash(str(receipt['selector']))[:24]}.json"
    )
    from .config import atomic_write_text

    atomic_write_text(
        receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    )
    _prune_forget_receipts(receipt_path.parent)
    _emit(receipt, args.json)
    return 0


def command_retention(args: argparse.Namespace, home: Path) -> int:
    config = _load(home)
    days = args.days if args.days is not None else config.archive_retention_days
    if days < 1:
        raise ValueError("retention days must be at least 1")
    before = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    store = BrainStore(config.database_path)
    rows = [
        *store.expired_documents("session", before),
        *store.expired_documents("handoff", before),
    ]
    raw_evidence = store.expired_raw_evidence_counts(before)
    raw_count = sum(raw_evidence.values())
    pending_relation_cleanups = len(store.pending_relation_cleanups())
    preview = {
        "status": "ok",
        "days": days,
        "before": before,
        "documents": [
            {
                "id": str(row["document_id"]),
                "kind": str(row["kind"]),
                "path": str(row["path"]),
            }
            for row in rows
        ],
        "raw_evidence": raw_evidence,
        "pending_relation_cleanups": pending_relation_cleanups,
        "count": len(rows) + raw_count,
        "dry_run": not args.apply,
    }
    if not args.apply:
        _emit(preview, args.json)
        return 0
    compacted_sessions = store.compact_empty_sessions("retention")
    if (
        not rows
        and raw_count == 0
        and pending_relation_cleanups == 0
        and compacted_sessions == 0
    ):
        _emit(preview, args.json)
        return 0

    store.mark_index_dirty()
    paths = [str(row["path"]) for row in rows]
    _erase_owned_paths(config, paths)
    receipts = [
        store.forget_document(
            str(row["document_id"]),
            "retention",
            preserve_adaptive=True,
        )
        for row in rows
    ]
    raw_deleted = store.prune_expired_raw_evidence(before)
    compacted_sessions += store.compact_empty_sessions("retention")
    _erase_owned_paths(
        config,
        [
            str(path)
            for receipt in receipts
            for path in receipt.get("paths", [])
        ],
    )
    curator = Curator(
        config,
        store,
        WikimapAdapter(config.vault_path, config.wikimap_command),
    )
    relation_cleanups = _drain_relation_cleanup_outbox(curator, store)
    store.checkpoint()
    index_updated = curator.update_index()
    preview.update(
        {
            "dry_run": False,
            "deleted": len(receipts) + sum(raw_deleted.values()),
            "raw_deleted": raw_deleted,
            "compacted_sessions": compacted_sessions,
            "relation_cleanups": relation_cleanups,
            "index_updated": index_updated,
        }
    )
    _emit(preview, args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brainctl",
        description="Local-first project memory bridge for Claude Code, Codex, and Grok.",
    )
    parser.add_argument("--home", help="Override WIKIBRAIN_HOME")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command_name", required=True)

    init = commands.add_parser("init", help="Initialize the brain and install hooks")
    init.add_argument("--vault")
    init.add_argument(
        "--workspace",
        action="append",
        default=[],
        help=(
            "Allowlist a workspace root (repeatable); defaults to the current "
            "user's home directory on first initialization"
        ),
    )
    init.add_argument("--clients", type=_clients, default=["claude", "codex"])
    init.add_argument("--no-hooks", action="store_true")
    init.add_argument("--no-skills", action="store_true")
    init.add_argument("--command", help="brainctl executable to write into hook configs")
    init.add_argument("--claude-settings")
    init.add_argument("--codex-hooks")
    init.add_argument("--grok-hooks")
    init.add_argument("--claude-skill-dir")
    init.add_argument("--agents-skill-dir")
    init.add_argument("--grok-skill-dir")
    init.add_argument("--dry-run", action="store_true")
    init.add_argument("--force", action="store_true")
    init.add_argument("--json", action="store_true")

    setup = commands.add_parser("setup", help="Install or refresh agent hooks")
    setup.add_argument("--clients", type=_clients, default=["claude", "codex"])
    setup.add_argument("--command")
    setup.add_argument("--claude-settings")
    setup.add_argument("--codex-hooks")
    setup.add_argument("--grok-hooks")
    setup.add_argument("--claude-skill-dir")
    setup.add_argument("--agents-skill-dir")
    setup.add_argument("--grok-skill-dir")
    setup.add_argument("--no-skills", action="store_true")
    setup.add_argument("--dry-run", action="store_true")
    setup.add_argument("--json", action="store_true")

    hook = commands.add_parser("hook", help=argparse.SUPPRESS)
    hook.add_argument(
        "--provider", choices=["claude", "codex", "grok"], required=True
    )

    hooks = commands.add_parser("hooks", help="Inspect or uninstall hooks")
    hooks_commands = hooks.add_subparsers(dest="hooks_command", required=True)
    hooks_status = hooks_commands.add_parser("status")
    hooks_status.add_argument(
        "--clients", type=_clients, default=["claude", "codex"]
    )
    hooks_status.add_argument("--claude-settings")
    hooks_status.add_argument("--codex-hooks")
    hooks_status.add_argument("--grok-hooks")
    hooks_status.add_argument("--json", action="store_true")
    hooks_remove = hooks_commands.add_parser("uninstall")
    hooks_remove.add_argument("--clients", type=_clients, default=["claude", "codex"])
    hooks_remove.add_argument("--claude-settings")
    hooks_remove.add_argument("--codex-hooks")
    hooks_remove.add_argument("--grok-hooks")
    hooks_remove.add_argument("--dry-run", action="store_true")
    hooks_remove.add_argument("--json", action="store_true")

    skills = commands.add_parser("skills", help="Inspect or uninstall agent skills")
    skills_commands = skills.add_subparsers(dest="skills_command", required=True)
    skills_status_parser = skills_commands.add_parser("status")
    skills_status_parser.add_argument(
        "--clients", type=_clients, default=["claude", "codex"]
    )
    skills_status_parser.add_argument("--claude-skill-dir")
    skills_status_parser.add_argument("--agents-skill-dir")
    skills_status_parser.add_argument("--grok-skill-dir")
    skills_status_parser.add_argument("--json", action="store_true")
    skills_remove = skills_commands.add_parser("uninstall")
    skills_remove.add_argument(
        "--clients", type=_clients, default=["claude", "codex"]
    )
    skills_remove.add_argument("--claude-skill-dir")
    skills_remove.add_argument("--agents-skill-dir")
    skills_remove.add_argument("--grok-skill-dir")
    skills_remove.add_argument("--dry-run", action="store_true")
    skills_remove.add_argument("--json", action="store_true")

    remember = commands.add_parser("remember", help="Save an explicit durable memory")
    remember.add_argument("text", nargs="?")
    remember.add_argument("--title")
    remember.add_argument(
        "--relates-to",
        action="append",
        default=[],
        metavar="DOCUMENT_ID",
        help="Link supporting or related memory (repeatable)",
    )
    remember.add_argument(
        "--supersedes",
        action="append",
        default=[],
        metavar="DOCUMENT_ID",
        help="Replace an outdated memory in recall (repeatable)",
    )
    memory_scope = remember.add_mutually_exclusive_group()
    memory_scope.add_argument("--workspace")
    memory_scope.add_argument(
        "--global",
        dest="global_memory",
        action="store_true",
        help="Intentionally recall this memory in every allowed project",
    )
    remember.add_argument("--json", action="store_true")

    recall = commands.add_parser("recall", help="Recall relevant local context")
    recall.add_argument("query", nargs="?")
    recall.add_argument("--workspace")
    recall.add_argument("--json", action="store_true")

    pause = commands.add_parser("pause", help="Pause capture and recall")
    pause.add_argument("--json", action="store_true")
    resume = commands.add_parser("resume", help="Resume capture and recall")
    resume.add_argument("--json", action="store_true")
    status = commands.add_parser("status", help="Show brain and hook status")
    status.add_argument("--json", action="store_true")
    doctor = commands.add_parser("doctor", help="Check storage, Wikimap, and hooks")
    doctor.add_argument("--offline", action="store_true")
    doctor.add_argument(
        "--skip-hooks",
        action="store_true",
        help="Skip hook registration checks (for isolated packaging tests)",
    )
    doctor.add_argument("--json", action="store_true")

    reindex = commands.add_parser(
        "reindex", help="Rebuild Wikimap and mark the disposable index clean"
    )
    reindex.add_argument("--json", action="store_true")

    forget = commands.add_parser("forget", help="Preview or erase owned memories")
    selector = forget.add_mutually_exclusive_group(required=True)
    selector.add_argument("--document")
    selector.add_argument("--session")
    forget.add_argument(
        "--provider",
        choices=["claude", "codex", "grok"],
        help="Disambiguate --session when clients reuse the same session ID",
    )
    forget.add_argument("--reason", default="user-request")
    forget.add_argument(
        "--cascade",
        action="store_true",
        help="For a document with lineage, erase its entire source session",
    )
    forget.add_argument("--apply", action="store_true")
    forget.add_argument("--json", action="store_true")

    retention = commands.add_parser(
        "retention", help="Preview or prune expired conversation evidence"
    )
    retention.add_argument("--days", type=int)
    retention.add_argument("--apply", action="store_true")
    retention.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    home = Path(args.home).expanduser().resolve() if args.home else default_home()
    try:
        if args.command_name == "hook":
            return run_hook_command(args.provider, home=home)
        if args.command_name == "init":
            return command_init(args, home)
        if args.command_name == "setup":
            return command_setup(args, home)
        if args.command_name == "hooks":
            return command_hooks(args, home)
        if args.command_name == "skills":
            return command_skills(args)
        if args.command_name == "remember":
            return command_remember(args, home)
        if args.command_name == "recall":
            return command_recall(args, home)
        if args.command_name == "pause":
            return command_pause(args, home, True)
        if args.command_name == "resume":
            return command_pause(args, home, False)
        if args.command_name == "status":
            return command_status(args, home)
        if args.command_name == "doctor":
            return command_doctor(args, home)
        if args.command_name == "reindex":
            return command_reindex(args, home)
        if args.command_name == "forget":
            return command_forget(args, home)
        if args.command_name == "retention":
            return command_retention(args, home)
    except (
        RuntimeError,
        ValueError,
        OSError,
        sqlite3.Error,
        json.JSONDecodeError,
        WikimapError,
    ) as error:
        print(f"brainctl: {error}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
