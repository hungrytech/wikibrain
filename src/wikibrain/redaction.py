from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


REDACTED = "[REDACTED]"

_SENSITIVE_KEY_NAME = (
    r"(?:"
    r"_?(?:[A-Za-z][A-Za-z0-9]*[_-])*"
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]KEY|PRIVATE[_-]KEY|ACCESS[_-]KEY)"
    r"(?:[_-][A-Za-z0-9]+)*"
    r"|_?(?-i:apiKey|clientSecret|authToken|accessToken|refreshToken|"
    r"privateKey|accessKey)"
    r")"
)

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private-key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----.*?"
            r"-----END (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    (
        "sensitive-env",
        re.compile(
            r"(?im)^(\s*(?:export\s+)?"
            + _SENSITIVE_KEY_NAME
            + r"\s*=\s*)([\"']?)([^\n\"']+)\2"
        ),
    ),
    (
        "sensitive-key-value",
        re.compile(
            r"(?ix)"
            r"(?<![A-Za-z0-9_])"
            r"(?P<prefix>"
            r"(?P<key_quote>[\"']?)"
            + _SENSITIVE_KEY_NAME
            + r"(?P=key_quote)\s*:\s*"
            r")"
            r"(?:"
            r"\"(?P<double_value>(?:\\.|[^\"\\\n])+)\""
            r"|'(?P<single_value>(?:\\.|[^'\\\n])+)'"
            r"|(?P<bare_value>[^,\]\}\n]+)"
            r")"
        ),
    ),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b")),
    ("stripe-live-key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b")),
    ("pypi-token", re.compile(r"\bpypi-[A-Za-z0-9_-]{20,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")),
    (
        "google-api-key",
        re.compile(
            r"(?<![A-Za-z0-9_-])AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"
        ),
    ),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "slack-token",
        re.compile(r"\b(?:xox[baprs]|xapp)-[A-Za-z0-9-]{10,}\b"),
    ),
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\."
            r"[A-Za-z0-9_-]{8,}\b"
        ),
    ),
    (
        "discord-token",
        re.compile(
            r"\b[A-Za-z0-9_-]{23,30}\.[A-Za-z0-9_-]{6}\."
            r"[A-Za-z0-9_-]{25,110}\b"
        ),
    ),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("npm-token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    (
        "authorization",
        re.compile(r"(?im)\b(authorization\s*[:=]\s*)(?:bearer|basic)\s+\S+"),
    ),
    (
        "credential-assignment",
        re.compile(
            r"(?im)\b(password|passwd|secret|api[_-]?key|access[_-]?token|"
            r"refresh[_-]?token|client[_-]?secret)\b(\s*[:=]\s*)"
            r"([\"']?)([^\s,\"']{6,}|[^\"'\n]{6,})\3"
        ),
    ),
    (
        "credential-url",
        re.compile(r"\b([a-z][a-z0-9+.-]*://[^:\s/@]+:)([^@\s/]+)(@)", re.I),
    ),
)


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    count: int
    kinds: tuple[str, ...]


def redact_text(value: str, limit: int | None = None) -> RedactionResult:
    text = value
    count = 0
    kinds: list[str] = []
    for name, pattern in _PATTERNS:
        if name == "authorization":
            text, matches = pattern.subn(lambda match: match.group(1) + REDACTED, text)
        elif name == "sensitive-env":
            text, matches = pattern.subn(
                lambda match: (
                    f"{match.group(1)}{match.group(2)}"
                    f"{REDACTED}{match.group(2)}"
                ),
                text,
            )
        elif name == "sensitive-key-value":
            def replace_key_value(match: re.Match[str]) -> str:
                if match.group("double_value") is not None:
                    quote = '"'
                elif match.group("single_value") is not None:
                    quote = "'"
                else:
                    quote = match.group("key_quote")
                return f"{match.group('prefix')}{quote}{REDACTED}{quote}"

            text, matches = pattern.subn(replace_key_value, text)
        elif name == "credential-assignment":
            text, matches = pattern.subn(
                lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
                text,
            )
        elif name == "credential-url":
            text, matches = pattern.subn(
                lambda match: f"{match.group(1)}{REDACTED}{match.group(3)}",
                text,
            )
        else:
            text, matches = pattern.subn(REDACTED, text)
        if matches:
            count += matches
            kinds.append(name)
    if limit is not None and len(text) > limit:
        omitted = len(text) - limit
        text = f"{text[:limit]}\n… [{omitted} chars omitted]"
    return RedactionResult(text=text, count=count, kinds=tuple(kinds))


def sanitize_value(value: Any, max_chars: int = 4_000, depth: int = 0) -> Any:
    if depth > 4:
        return "[TRUNCATED]"
    if isinstance(value, str):
        return redact_text(value, max_chars).text
    if isinstance(value, dict):
        return {
            str(key)[:120]: sanitize_value(item, max_chars, depth + 1)
            for key, item in list(value.items())[:100]
            if str(key).lower() not in {"tool_response", "transcript", "content"}
        }
    if isinstance(value, list):
        return [sanitize_value(item, max_chars, depth + 1) for item in value[:100]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact_text(str(value), max_chars).text
