from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .models import NormalizedEvent
from .redaction import sanitize_value


SUPPORTED_PROVIDERS = {"claude", "codex"}
SUPPORTED_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PostToolUse",
    "Stop",
    "PostCompact",
}


def _string(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _fallback_session(provider: str, payload: dict[str, Any], cwd: str) -> str:
    source = _string(payload.get("transcript_path")) or cwd
    digest = hashlib.sha256(f"{provider}\0{source}".encode()).hexdigest()[:20]
    return f"unknown-{digest}"


def _tool_pointer(payload: dict[str, Any], max_chars: int) -> dict[str, Any]:
    raw_input = payload.get("tool_input")
    if not isinstance(raw_input, dict):
        raw_input = payload.get("input")
    if not isinstance(raw_input, dict):
        raw_input = {}
    selected: dict[str, Any] = {}
    allowed = (
        "file_path",
        "path",
        "workdir",
    )
    for key in allowed:
        if key in raw_input:
            selected[key] = sanitize_value(raw_input[key], min(max_chars, 1_000))
    return selected


def normalize_hook(
    provider: str,
    payload: dict[str, Any],
    *,
    max_chars: int = 40_000,
) -> NormalizedEvent:
    provider = provider.lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported provider: {provider}")
    event_name = _string(payload.get("hook_event_name"))
    if event_name not in SUPPORTED_EVENTS:
        raise ValueError(f"unsupported hook event: {event_name!r}")
    cwd = _string(payload.get("cwd")) or str(Path.cwd())
    supplied_session_id = _string(payload.get("session_id"))
    session_id = supplied_session_id or _fallback_session(provider, payload, cwd)
    turn_id = _string(payload.get("turn_id"))
    prompt = _string(payload.get("prompt"))
    assistant = _string(payload.get("last_assistant_message"))
    compact_summary = _string(payload.get("compact_summary"))
    background_tasks = payload.get("background_tasks")
    background_work_pending = bool(
        provider == "claude"
        and isinstance(background_tasks, list)
        and background_tasks
    )
    tool_name = _string(payload.get("tool_name"))
    tool_use_id = _string(payload.get("tool_use_id"))
    metadata_keys = (
        "source",
        "trigger",
        "model",
        "permission_mode",
        "transcript_path",
        "stop_hook_active",
    )
    metadata = {
        key: sanitize_value(payload[key], min(max_chars, 2_000))
        for key in metadata_keys
        if key in payload
    }
    return NormalizedEvent(
        provider=provider,
        name=event_name,
        session_id=session_id,
        turn_id=turn_id,
        cwd=cwd,
        session_id_is_fallback=supplied_session_id is None,
        prompt=prompt,
        assistant_message=assistant,
        compact_summary=compact_summary,
        background_work_pending=background_work_pending,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        tool_pointer=_tool_pointer(payload, max_chars),
        raw_metadata=metadata,
    )


def hook_output(event_name: str, context: str = "") -> dict[str, Any]:
    if context and event_name in {"SessionStart", "UserPromptSubmit"}:
        return {
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "additionalContext": context,
            }
        }
    return {}
