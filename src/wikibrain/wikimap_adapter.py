from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from .models import SearchHit


class WikimapError(RuntimeError):
    pass


class WikimapAdapter:
    """Calls only Wikimap's public CLI; its internal files are never opened."""

    def __init__(self, vault: Path, command: str = "wikimap", timeout: float = 3.0):
        self.vault = vault
        self.command = command
        self.timeout = timeout

    @property
    def available(self) -> bool:
        command_path = Path(self.command).expanduser()
        if (
            command_path.is_absolute()
            or "/" in self.command
            or "\\" in self.command
        ):
            if command_path.suffix.casefold() == ".py":
                return command_path.is_file()
            return (
                command_path.is_file()
                and os.access(command_path, os.X_OK)
            )
        return shutil.which(self.command) is not None

    def _command_arguments(self) -> list[str]:
        command_path = Path(self.command).expanduser()
        if (
            command_path.suffix.casefold() == ".py"
            and command_path.is_file()
        ):
            return [sys.executable, str(command_path)]
        return [self.command]

    def _run(self, arguments: list[str], timeout: float | None = None) -> str:
        if not self.available:
            raise WikimapError(f"{self.command!r} is not installed")
        operation = arguments[0] if arguments else "command"
        try:
            options: dict[str, Any] = {
                "cwd": self.vault,
                "check": False,
                "capture_output": True,
                "text": True,
                "timeout": timeout or self.timeout,
                "shell": False,
            }
            if os.name == "posix":
                options["umask"] = 0o077
            completed = subprocess.run(
                [*self._command_arguments(), *arguments],
                **options,
            )
        except subprocess.TimeoutExpired as error:
            raise WikimapError(f"wikimap {operation} timed out") from error
        except OSError as error:
            raise WikimapError(
                f"wikimap {operation} could not run: {type(error).__name__}"
            ) from error
        if completed.returncode != 0:
            detail = ""
            if operation != "search":
                detail = (completed.stderr or completed.stdout).strip()[:1_000]
            suffix = f": {detail}" if detail else ""
            raise WikimapError(
                f"wikimap {operation} failed ({completed.returncode}){suffix}"
            )
        return completed.stdout

    def version(self) -> str | None:
        if not self.available:
            return None
        for arguments in (["--version"], ["version"]):
            try:
                text = self._run(arguments, timeout=2.0).strip()
                if text:
                    return text.splitlines()[0]
            except WikimapError:
                continue
        return None

    def update(self) -> str:
        return self._run(["update"], timeout=max(self.timeout, 15.0))

    def doctor(self) -> dict[str, Any]:
        output = self._run(
            ["doctor", "--json"],
            timeout=max(self.timeout, 10.0),
        )
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as error:
            raise WikimapError("wikimap doctor did not return valid JSON") from error
        if not isinstance(payload, dict) or payload.get("healthy") is not True:
            detail = json.dumps(payload, ensure_ascii=False)[:1_000]
            raise WikimapError(f"wikimap doctor reported unhealthy: {detail}")
        return payload

    def search(self, query: str, limit: int = 6) -> list[SearchHit]:
        output = self._run(["search", query, "-n", str(limit), "--json"])
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as error:
            raise WikimapError("wikimap search did not return valid JSON") from error
        return list(_parse_search_payload(payload, limit))


def _parse_search_payload(payload: Any, limit: int) -> Iterable[SearchHit]:
    candidates: list[dict[str, Any]] = []
    if isinstance(payload, list):
        candidates.extend(item for item in payload if isinstance(item, dict))
    elif isinstance(payload, dict):
        for key in ("results", "matches", "documents", "notes", "hits"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))
        if not candidates and any(
            key in payload for key in ("path", "file", "source", "answer", "snippet")
        ):
            candidates.append(payload)

    seen: set[tuple[str, int | None, str]] = set()
    for item in candidates:
        sources = item.get("sources")
        source = item.get("path") or item.get("file") or item.get("source")
        if not source and isinstance(sources, list) and sources:
            source = sources[0]
        path = str(source or "wikimap-note")
        line_value = item.get("line") or item.get("line_number")
        try:
            line = int(line_value) if line_value is not None else None
        except (TypeError, ValueError):
            line = None
        snippet_value = (
            item.get("snippet")
            or item.get("answer")
            or item.get("text")
            or item.get("content")
            or item.get("matched")
            or item.get("question")
            or ""
        )
        if isinstance(snippet_value, list):
            snippet = "\n".join(str(part) for part in snippet_value[:5])
        else:
            snippet = str(snippet_value)
        title = str(
            item.get("title")
            or item.get("heading")
            or item.get("question")
            or Path(path).stem
        )
        score_value = item.get("score")
        try:
            score = float(score_value) if score_value is not None else None
        except (TypeError, ValueError):
            score = None
        marker = (path, line, snippet)
        if marker in seen:
            continue
        seen.add(marker)
        yield SearchHit(
            path=path,
            line=line,
            title=title,
            snippet=snippet[:2_000],
            score=score,
            kind="note" if "answer" in item else "document",
        )
        if len(seen) >= limit:
            return


def fallback_search(vault: Path, query: str, limit: int = 6) -> list[SearchHit]:
    """Small degraded-mode search used only when the Wikimap CLI is unavailable."""

    terms = {
        term.casefold()
        for term in re.findall(r"[\w가-힣]{2,}", query, flags=re.UNICODE)
    }
    if not terms:
        return []
    ranked: list[tuple[int, Path, str]] = []
    for path in vault.rglob("*.md"):
        if path.is_symlink() or ".wikimap" in path.parts or path.name == "MAP.md":
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                text = handle.read(200_000)
        except (OSError, UnicodeError):
            continue
        folded = text.casefold()
        score = sum(folded.count(term) for term in terms)
        if score:
            matching = next(
                (line.strip() for line in text.splitlines() if any(t in line.casefold() for t in terms)),
                "",
            )
            ranked.append((score, path, matching))
    ranked.sort(key=lambda item: (-item[0], str(item[1])))
    return [
        SearchHit(
            path=str(path.relative_to(vault)),
            line=None,
            title=path.stem,
            snippet=snippet[:2_000],
            score=float(score),
        )
        for score, path, snippet in ranked[:limit]
    ]
