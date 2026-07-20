from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class NormalizedEvent:
    provider: str
    name: str
    session_id: str
    turn_id: str | None
    cwd: str
    prompt: str | None = None
    assistant_message: str | None = None
    compact_summary: str | None = None
    background_work_pending: bool = False
    tool_name: str | None = None
    tool_use_id: str | None = None
    tool_pointer: dict[str, Any] = field(default_factory=dict)
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HookResult:
    captured: bool = False
    duplicate: bool = False
    context: str = ""
    reason: str = ""


@dataclass(slots=True)
class SearchHit:
    path: str
    line: int | None
    title: str
    snippet: str
    score: float | None = None
    kind: str = "document"
