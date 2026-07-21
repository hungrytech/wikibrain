from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

from .config import BrainConfig, atomic_write_text
from .redaction import redact_text
from .storage import (
    BrainStore,
    explicit_memory_id,
    handoff_document_id,
    stable_hash,
    turn_document_id,
)
from .wikimap_adapter import WikimapAdapter, WikimapError


_REMEMBER_PATTERN = re.compile(
    r"^\s*(?:기억(?:해|해줘|해\s*두|해둬)|잊지\s*마|"
    r"(?:please\s+)?remember(?:\s+this)?\b|don't forget\b)",
    re.IGNORECASE,
)


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _safe_name(value: str, length: int = 36) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9가-힣._-]+", "-", value).strip("-._")
    return (cleaned or "item")[:length]


class Curator:
    def __init__(
        self,
        config: BrainConfig,
        store: BrainStore,
        wikimap: WikimapAdapter,
    ):
        self.config = config
        self.store = store
        self.wikimap = wikimap

    def _write(self, relative: Path, content: str) -> Path:
        path = self.config.vault_path / relative
        atomic_write_text(path, content)
        return path

    def archive_turn(
        self, turn: Mapping[str, Any] | sqlite3.Row
    ) -> tuple[str, Path]:
        completed = str(turn["completed_at"] or turn["created_at"])
        try:
            moment = datetime.fromisoformat(completed)
        except ValueError:
            moment = datetime.now(UTC)
        document_id = turn_document_id(
            str(turn["provider"]),
            str(turn["session_id"]),
            str(turn["turn_key"]),
            str(turn["cwd"]),
        )
        relative = (
            Path("sessions")
            / moment.strftime("%Y")
            / moment.strftime("%m")
            / moment.strftime("%d")
            / f"{_safe_name(str(turn['provider']))}-{document_id}.md"
        )
        prompt = str(turn["prompt"] or "(prompt unavailable)")
        response = str(turn["response"] or "(response unavailable)")
        content = f"""---
id: {_yaml_string(document_id)}
type: "session"
provider: {_yaml_string(str(turn["provider"]))}
session_id: {_yaml_string(str(turn["session_id"]))}
turn_id: {_yaml_string(str(turn["turn_key"]))}
workspace: {_yaml_string(str(turn["cwd"]))}
captured_at: {_yaml_string(completed)}
---

# Conversation handoff

## User

{prompt}

## Assistant

{response}
"""
        path = self._write(relative, content)
        registered = self.store.register_document(
            document_id,
            "session",
            path,
            provider=str(turn["provider"]),
            session_id=str(turn["session_id"]),
            turn_key=str(turn["turn_key"]),
            workspace=str(turn["cwd"]),
            metadata={"captured_at": completed},
        )
        if not registered:
            path.unlink(missing_ok=True)
        return document_id, path

    def archive_handoff(
        self,
        provider: str,
        session_id: str,
        workspace: str,
        summary: str,
    ) -> tuple[str, Path]:
        now = datetime.now(UTC)
        document_id = handoff_document_id(
            provider,
            session_id,
            workspace,
            summary,
        )
        relative = (
            Path("handoffs")
            / now.strftime("%Y")
            / now.strftime("%m")
            / f"{_safe_name(provider)}-{document_id}.md"
        )
        content = f"""---
id: {_yaml_string(document_id)}
type: "handoff"
provider: {_yaml_string(provider)}
session_id: {_yaml_string(session_id)}
workspace: {_yaml_string(workspace)}
captured_at: {_yaml_string(now.isoformat(timespec="milliseconds"))}
---

# Compaction handoff

{summary}
"""
        path = self._write(relative, content)
        registered = self.store.register_document(
            document_id,
            "handoff",
            path,
            provider=provider,
            session_id=session_id,
            workspace=workspace,
        )
        if not registered:
            path.unlink(missing_ok=True)
        return document_id, path

    def remove_relation_target(self, path: Path, target_document_id: str) -> bool:
        """Remove a forgotten target ID from owned memory frontmatter."""
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self.config.vault_path.resolve())
        except (OSError, RuntimeError, ValueError):
            raise ValueError("relation source path is outside the vault") from None
        try:
            text = resolved.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False
        if not text.startswith("---\n"):
            raise ValueError(f"relation source has no frontmatter: {relative}")
        end = text.find("\n---\n", 4)
        if end < 0:
            raise ValueError(f"relation source has malformed frontmatter: {relative}")
        frontmatter = text[4:end]
        try:
            root = yaml.compose(frontmatter, Loader=yaml.SafeLoader)
        except yaml.YAMLError as error:
            raise ValueError(f"malformed frontmatter in {relative}") from error
        if not isinstance(root, MappingNode):
            raise ValueError(f"relation source has non-mapping frontmatter: {relative}")

        replacements: list[tuple[int, int, str]] = []
        for key_node, value_node in root.value:
            if not isinstance(key_node, ScalarNode) or key_node.value not in {
                "relates_to",
                "supersedes",
            }:
                continue
            field = key_node.value
            if not isinstance(value_node, SequenceNode) or not all(
                isinstance(value, ScalarNode)
                and value.tag == "tag:yaml.org,2002:str"
                for value in value_node.value
            ):
                raise ValueError(f"malformed relation list in {relative}: {field}")
            if value_node.start_mark.index < key_node.end_mark.index:
                raise ValueError(f"unsupported relation alias in {relative}: {field}")
            values = [value.value for value in value_node.value]
            remaining = [value for value in values if value != target_document_id]
            if len(remaining) == len(values):
                continue
            rendered = "[" + ", ".join(_yaml_string(value) for value in remaining) + "]"
            if value_node.start_mark.line > key_node.start_mark.line:
                rendered += "\n"
            replacements.append(
                (value_node.start_mark.index, value_node.end_mark.index, rendered)
            )

        if not replacements:
            return False
        updated_frontmatter = frontmatter
        for start, finish, rendered in sorted(replacements, reverse=True):
            updated_frontmatter = (
                updated_frontmatter[:start] + rendered + updated_frontmatter[finish:]
            )
        self._write(relative, "---\n" + updated_frontmatter + text[end:])
        return True

    def remember(
        self,
        text: str,
        *,
        title: str | None = None,
        workspace: str | None = None,
        source: str = "manual",
        update_index: bool = True,
        document_id: str | None = None,
        captured_at: str | None = None,
        provider: str | None = None,
        session_id: str | None = None,
        turn_key: str | None = None,
        relates_to: list[str] | None = None,
        supersedes: list[str] | None = None,
    ) -> tuple[str, Path]:
        if workspace is not None:
            scope = self.config.scope_for(workspace)
            if scope is None:
                raise ValueError("memory workspace is outside the allowlist")
            workspace = str(scope)
        redacted = redact_text(text, self.config.max_field_chars)
        try:
            now = datetime.fromisoformat(captured_at) if captured_at else datetime.now(UTC)
        except ValueError:
            now = datetime.now(UTC)
        proposed_title = title or next(
            (line.strip("# ").strip() for line in redacted.text.splitlines() if line.strip()),
            "Memory",
        )
        title_redaction = redact_text(proposed_title, 500)
        safe_title = " ".join(title_redaction.text.split())[:200] or "Memory"
        timestamp = now.isoformat(timespec="milliseconds")
        document_id = document_id or (
            "memory-" + stable_hash(safe_title, redacted.text, timestamp)[:24]
        )
        relations = {
            "relates-to": list(dict.fromkeys(relates_to or [])),
            "supersedes": list(dict.fromkeys(supersedes or [])),
        }
        relations = {key: value for key, value in relations.items() if value}
        if relations:
            self.store.validate_relation_targets(
                document_id,
                workspace,
                relations,
            )
        relative = (
            Path("memories")
            / now.strftime("%Y")
            / now.strftime("%m")
            / f"{_safe_name(safe_title, 48)}-{document_id}.md"
        )
        relation_frontmatter = ""
        if relations.get("relates-to"):
            relation_frontmatter += "relates_to: [" + ", ".join(
                _yaml_string(value) for value in relations["relates-to"]
            ) + "]\n"
        if relations.get("supersedes"):
            relation_frontmatter += "supersedes: [" + ", ".join(
                _yaml_string(value) for value in relations["supersedes"]
            ) + "]\n"
        content = f"""---
id: {_yaml_string(document_id)}
type: "memory"
title: {_yaml_string(safe_title)}
source: {_yaml_string(source)}
workspace: {_yaml_string(workspace or "")}
captured_at: {_yaml_string(timestamp)}
{relation_frontmatter}---

# {safe_title}

{redacted.text}
"""
        target_path = self.config.vault_path / relative
        previous_content = (
            target_path.read_text(encoding="utf-8") if target_path.exists() else None
        )
        path = self._write(relative, content)
        try:
            registered = self.store.register_document(
                document_id,
                "memory",
                path,
                provider=provider,
                session_id=session_id,
                turn_key=turn_key,
                workspace=workspace,
                metadata={
                    "source": source,
                    "redactions": redacted.count + title_redaction.count,
                },
                relations=relations,
            )
        except Exception:
            if previous_content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_text(path, previous_content)
            raise
        if not registered:
            if previous_content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_text(path, previous_content)
        if update_index:
            self.update_index()
        return document_id, path

    def maybe_promote_explicit(
        self, turn: Mapping[str, Any] | sqlite3.Row
    ) -> tuple[str, Path] | None:
        prompt = str(turn["prompt"] or "")
        if not _REMEMBER_PATTERN.search(prompt):
            return None
        provider = str(turn["provider"])
        session_id = str(turn["session_id"])
        turn_key = str(turn["turn_key"])
        document_id = explicit_memory_id(
            provider,
            session_id,
            turn_key,
            str(turn["cwd"]),
        )
        if self.store.document(document_id):
            self.store.complete_promotion(provider, session_id, turn_key)
            return None
        if self.store.tombstone_receipt(f"document:{document_id}"):
            self.store.complete_promotion(provider, session_id, turn_key)
            return None
        if not self.store.queue_promotion(provider, session_id, turn_key):
            return None
        promoted = self.remember(
            f"User request:\n{prompt}",
            title="Explicitly requested memory",
            workspace=str(turn["cwd"]),
            source=f"{provider}:{session_id}:{turn_key}",
            update_index=False,
            document_id=document_id,
            captured_at=str(turn["completed_at"] or turn["created_at"]),
            provider=provider,
            session_id=session_id,
            turn_key=turn_key,
        )
        if self.store.document(document_id) is None:
            self.store.complete_promotion(provider, session_id, turn_key)
            return None
        self.store.complete_promotion(provider, session_id, turn_key)
        return promoted

    def update_index(self) -> bool:
        generation = self.store.index_generation()
        try:
            self.wikimap.update()
            return self.store.mark_index_clean(generation)
        except WikimapError:
            return False
