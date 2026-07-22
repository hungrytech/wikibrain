from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .models import NormalizedEvent
from .redaction import sanitize_value


SUPPORTED_PROVIDERS = {"claude", "codex", "grok"}
SUPPORTED_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PostToolUse",
    "Stop",
    "PostCompact",
}
EVENT_NAME_ALIASES = {
    "session_start": "SessionStart",
    "user_prompt_submit": "UserPromptSubmit",
    "post_tool_use": "PostToolUse",
    "stop": "Stop",
    "post_compact": "PostCompact",
}


def _string(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _value(payload: dict[str, Any], snake_case: str, camel_case: str) -> Any:
    if snake_case in payload:
        return payload[snake_case]
    return payload.get(camel_case)


def _fallback_session(provider: str, payload: dict[str, Any], cwd: str) -> str:
    source = _string(_value(payload, "transcript_path", "transcriptPath")) or cwd
    digest = hashlib.sha256(f"{provider}\0{source}".encode()).hexdigest()[:20]
    return f"unknown-{digest}"


def _tool_pointer(payload: dict[str, Any], max_chars: int) -> dict[str, Any]:
    raw_input = _value(payload, "tool_input", "toolInput")
    if not isinstance(raw_input, dict):
        raw_input = payload.get("input")
    if not isinstance(raw_input, dict):
        raw_input = {}
    selected: dict[str, Any] = {}
    allowed = {
        "file_path": ("file_path", "filePath"),
        "path": ("path",),
        "workdir": ("workdir", "workingDirectory"),
    }
    for canonical, aliases in allowed.items():
        for key in aliases:
            if key in raw_input:
                selected[canonical] = sanitize_value(
                    raw_input[key], min(max_chars, 1_000)
                )
                break
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
    event_name = _string(_value(payload, "hook_event_name", "hookEventName"))
    event_name = EVENT_NAME_ALIASES.get(event_name or "", event_name)
    if event_name not in SUPPORTED_EVENTS:
        raise ValueError(f"unsupported hook event: {event_name!r}")
    cwd = _string(payload.get("cwd")) or str(Path.cwd())
    supplied_session_id = _string(_value(payload, "session_id", "sessionId"))
    session_id = supplied_session_id or _fallback_session(provider, payload, cwd)
    turn_id = _string(_value(payload, "turn_id", "turnId")) or _string(
        _value(payload, "prompt_id", "promptId")
    )
    prompt = _string(payload.get("prompt"))
    assistant = _string(
        _value(payload, "last_assistant_message", "lastAssistantMessage")
    )
    compact_summary = _string(_value(payload, "compact_summary", "compactSummary"))
    background_tasks = _value(payload, "background_tasks", "backgroundTasks")
    background_work_pending = bool(
        provider == "claude"
        and isinstance(background_tasks, list)
        and background_tasks
    )
    tool_name = _string(_value(payload, "tool_name", "toolName"))
    tool_use_id = _string(_value(payload, "tool_use_id", "toolUseId"))
    metadata_aliases = {
        "source": ("source", "source"),
        "trigger": ("trigger", "trigger"),
        "model": ("model", "model"),
        "permission_mode": ("permission_mode", "permissionMode"),
        "transcript_path": ("transcript_path", "transcriptPath"),
        "stop_hook_active": ("stop_hook_active", "stopHookActive"),
        "workspace_root": ("workspace_root", "workspaceRoot"),
        "prompt_id": ("prompt_id", "promptId"),
        "timestamp": ("timestamp", "timestamp"),
        "reason": ("reason", "reason"),
    }
    metadata = {}
    for canonical, (snake_case, camel_case) in metadata_aliases.items():
        value = _value(payload, snake_case, camel_case)
        if value is not None:
            metadata[canonical] = sanitize_value(value, min(max_chars, 2_000))
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
