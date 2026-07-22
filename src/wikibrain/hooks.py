from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from .config import (
    PRIVATE_FILE_MODE,
    BrainConfig,
    default_home,
    ensure_private_directory,
)
from .curation import Curator
from .hook_adapters import hook_output, normalize_hook
from .models import HookResult
from .recall import RecallService
from .redaction import redact_text
from .storage import BrainStore
from .wikimap_adapter import WikimapAdapter


def _safe_log(config: BrainConfig | None, message: str) -> None:
    if config is None:
        return
    try:
        ensure_private_directory(config.log_path.parent)
        with config.log_path.open("a", encoding="utf-8") as handle:
            handle.write(message.replace("\n", " ")[:500] + "\n")
        config.log_path.chmod(PRIVATE_FILE_MODE)
    except OSError:
        pass


def read_hook_payload(stream: BinaryIO, limit: int) -> dict[str, Any]:
    raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"hook payload exceeds {limit} bytes")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("hook stdin must be one UTF-8 JSON object") from error
    if not isinstance(payload, dict):
        raise ValueError("hook stdin must be a JSON object")
    return payload


def _drain_pending_archives(
    store: BrainStore,
    curator: Curator,
    *,
    max_items: int,
    time_budget: float,
) -> int:
    recovered = 0
    remaining = max_items
    started = time.monotonic()
    for turn in store.pending_completed_turns(limit=remaining):
        if remaining <= 0 or time.monotonic() - started >= time_budget:
            break
        remaining -= 1
        try:
            document_id, _ = curator.archive_turn(turn)
            if store.document(document_id) is not None:
                curator.maybe_promote_explicit(turn)
            recovered += 1
        except Exception:
            # Keep this item pending, but never let one poisoned archive block
            # unrelated sessions or the rest of the recovery queue.
            continue
    for handoff in store.pending_handoffs(limit=remaining):
        if remaining <= 0 or time.monotonic() - started >= time_budget:
            break
        remaining -= 1
        try:
            document_id, _ = curator.archive_handoff(
                str(handoff["provider"]),
                str(handoff["session_id"]),
                str(handoff["workspace"]),
                str(handoff["summary"]),
                event_key=str(handoff["event_key"]),
                captured_at=str(handoff["created_at"]),
            )
            if store.document(document_id) is not None:
                store.complete_handoff(str(handoff["event_key"]), document_id)
            else:
                store.discard_handoff(str(handoff["event_key"]))
            recovered += 1
        except Exception:
            continue
    for turn in store.pending_promotions(limit=remaining):
        if remaining <= 0 or time.monotonic() - started >= time_budget:
            break
        remaining -= 1
        try:
            curator.maybe_promote_explicit(turn)
            recovered += 1
        except Exception:
            continue
    return recovered


def process_hook(
    provider: str,
    payload: dict[str, Any],
    config: BrainConfig,
) -> tuple[dict[str, Any], HookResult]:
    event = normalize_hook(provider, payload, max_chars=config.max_field_chars)
    scope = config.scope_for(event.cwd)
    if config.paused or scope is None:
        return {}, HookResult(reason="paused-or-workspace-not-allowed")
    event.cwd = str(scope)

    store = BrainStore(config.database_path)
    if store.session_is_forgotten(event.provider, event.session_id):
        return {}, HookResult(reason="session-forgotten")
    wikimap = WikimapAdapter(config.vault_path, config.wikimap_command)
    recall = RecallService(config, store, wikimap)
    curator = Curator(config, store, wikimap)
    has_long_budget = event.name in {"Stop", "PostCompact"}
    _drain_pending_archives(
        store,
        curator,
        max_items=20 if has_long_budget else 4,
        time_budget=3.0 if has_long_budget else 1.0,
    )
    result = HookResult()
    consumer_session_id = None if event.session_id_is_fallback else event.session_id

    if event.name == "SessionStart":
        result.captured = store.capture_generic(event)
        result.context = recall.context(
            event.cwd,
            consumer_provider=event.provider,
            consumer_session_id=consumer_session_id,
        )
    elif event.name == "UserPromptSubmit":
        prompt = redact_text(event.prompt or "", config.max_field_chars)
        result.captured, event.turn_id = store.capture_prompt(
            event, prompt.text, prompt.count
        )
        result.duplicate = not result.captured
        result.context = recall.context(
            event.cwd,
            prompt.text,
            consumer_provider=event.provider,
            consumer_session_id=consumer_session_id,
        )
    elif event.name == "PostToolUse":
        result.captured = store.capture_generic(event)
        result.duplicate = not result.captured
    elif event.name == "Stop":
        if event.background_work_pending:
            result.reason = "background-work-pending"
            return {}, result
        response = redact_text(
            event.assistant_message or "(assistant message unavailable)",
            config.max_field_chars,
        )
        captured, turn = store.capture_stop(event, response.text, response.count)
        result.captured = captured
        result.duplicate = not captured
        needs_archive = bool(turn is not None and not turn["document_id"])
        promoted = None
        if turn is not None:
            # Durable, explicit user intent must not depend on the lower-value
            # conversation evidence archive succeeding first.
            promoted = curator.maybe_promote_explicit(turn)
            if needs_archive:
                curator.archive_turn(turn)
        if (
            config.update_on_stop
            and (captured or needs_archive or promoted or store.index_dirty())
        ):
            curator.update_index()
    elif event.name == "PostCompact":
        if event.compact_summary:
            summary = redact_text(
                event.compact_summary, config.max_field_chars
            )
            result.captured, handoff = store.capture_handoff(
                event,
                summary.text,
                summary.count,
            )
            result.duplicate = not result.captured
            pending = bool(handoff is not None and not handoff["document_id"])
            if pending and handoff is not None:
                document_id, _ = curator.archive_handoff(
                    str(handoff["provider"]),
                    str(handoff["session_id"]),
                    str(handoff["workspace"]),
                    str(handoff["summary"]),
                    event_key=str(handoff["event_key"]),
                    captured_at=str(handoff["created_at"]),
                )
                if store.document(document_id) is not None:
                    store.complete_handoff(str(handoff["event_key"]), document_id)
                else:
                    store.discard_handoff(str(handoff["event_key"]))
            if config.update_on_stop and (
                result.captured or pending or store.index_dirty()
            ):
                curator.update_index()
        else:
            result.captured = store.capture_generic(event)
            if config.update_on_stop and store.index_dirty():
                curator.update_index()

    return hook_output(event.name, result.context), result


def run_hook_command(
    provider: str,
    *,
    home: Path | None = None,
    stdin: BinaryIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    input_stream = stdin or sys.stdin.buffer
    output_stream = stdout or sys.stdout
    config: BrainConfig | None = None
    output: dict[str, Any] = {}
    try:
        config = BrainConfig.load(home or default_home())
        payload = read_hook_payload(input_stream, config.max_input_bytes)
        output, _ = process_hook(provider, payload, config)
    except Exception as error:  # A memory hook must never break the host agent.
        _safe_log(config, f"hook-error {type(error).__name__}: {error}")
        output = {}
    json.dump(output, output_stream, ensure_ascii=False)
    output_stream.write("\n")
    output_stream.flush()
    return 0
