from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


MANAGED_MARKER = "<!-- wikibrain-managed-skill:v1 -->"


def bundled_skill_path() -> Path:
    candidates = (
        Path(sys.prefix) / "share" / "wikibrain" / "skills" / "wikibrain",
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "wikibrain"
        / "skills"
        / "wikibrain",
    )
    for candidate in candidates:
        if (candidate / "SKILL.md").exists():
            return candidate
    raise FileNotFoundError("bundled WikiBrain skill is missing")


def default_skill_targets(clients: list[str]) -> dict[str, Path]:
    targets: dict[str, Path] = {}
    if "claude" in clients:
        targets["claude"] = Path.home() / ".claude" / "skills" / "wikibrain"
    if "codex" in clients:
        targets["agents"] = Path.home() / ".agents" / "skills" / "wikibrain"
    return targets


def _tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(value for value in path.rglob("*") if value.is_file()):
        digest.update(str(item.relative_to(path)).encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _managed(path: Path) -> bool:
    try:
        return MANAGED_MARKER in (path / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def install_skills(
    clients: list[str],
    *,
    source: Path | None = None,
    targets: dict[str, Path] | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    source = source or bundled_skill_path()
    selected = targets or default_skill_targets(clients)
    source_hash = _tree_hash(source)
    results: list[dict[str, Any]] = []
    for client, target in selected.items():
        if target.exists() and _tree_hash(target) == source_hash:
            results.append(
                {
                    "client": client,
                    "path": str(target),
                    "changes": 0,
                    "status": "current",
                    "dry_run": dry_run,
                }
            )
            continue
        if target.exists() and not _managed(target):
            results.append(
                {
                    "client": client,
                    "path": str(target),
                    "changes": 0,
                    "status": "preserved-custom-skill",
                    "dry_run": dry_run,
                }
            )
            continue
        backup: Path | None = None
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(
                tempfile.mkdtemp(prefix=".wikibrain-skill.", dir=target.parent)
            )
            shutil.rmtree(temporary)
            shutil.copytree(source, temporary)
            backup: Path | None = None
            if target.exists():
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                backup = target.with_name(f"wikibrain.{stamp}.bak")
                os.replace(target, backup)
            try:
                os.replace(temporary, target)
            except OSError:
                if backup is not None and not target.exists():
                    os.replace(backup, target)
                raise
            backup_pattern = re.compile(r"wikibrain\.\d{8}T\d{12}Z\.bak")
            backups = sorted(
                candidate
                for candidate in target.parent.glob("wikibrain.*.bak")
                if backup_pattern.fullmatch(candidate.name)
            )
            for expired in backups[:-3]:
                _remove_path(expired)
        results.append(
            {
                "client": client,
                "path": str(target),
                "changes": 1,
                "status": "would-install" if dry_run else "installed",
                "backup": str(backup) if backup else None,
                "dry_run": dry_run,
            }
        )
    return results


def uninstall_skills(
    clients: list[str],
    *,
    targets: dict[str, Path] | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    selected = targets or default_skill_targets(clients)
    results: list[dict[str, Any]] = []
    for client, target in selected.items():
        owned = target.exists() and _managed(target)
        if owned and not dry_run:
            _remove_path(target)
        results.append(
            {
                "client": client,
                "path": str(target),
                "changes": int(owned),
                "status": (
                    "would-remove"
                    if owned and dry_run
                    else "removed"
                    if owned
                    else "not-managed"
                ),
                "dry_run": dry_run,
            }
        )
    return results


def skill_status(
    clients: list[str],
    *,
    targets: dict[str, Path] | None = None,
) -> list[dict[str, Any]]:
    selected = targets or default_skill_targets(clients)
    return [
        {
            "client": client,
            "path": str(target),
            "installed": target.exists(),
            "managed": _managed(target),
        }
        for client, target in selected.items()
    ]
