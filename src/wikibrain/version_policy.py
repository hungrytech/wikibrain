from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from http.client import HTTPException
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from .config import atomic_write_text


POLICY_URL = (
    "https://raw.githubusercontent.com/hungrytech/wikibrain/"
    "main/release-policy.json"
)
CACHE_TTL = timedelta(hours=24)
CACHE_NAME = "release-policy-cache.json"
MAX_POLICY_BYTES = 64 * 1024
MAX_CACHE_BYTES = 128 * 1024
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@dataclass(frozen=True, slots=True)
class ReleasePolicy:
    schema_version: int
    latest_version: str
    minimum_supported_version: str
    updated_at: str

    def requires_upgrade(self, current_version: str) -> bool:
        return _version_tuple(current_version) < _version_tuple(
            self.minimum_supported_version
        )


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    state: str
    current_version: str
    minimum_supported_version: str | None
    latest_version: str | None
    source: str

    @property
    def upgrade_required(self) -> bool:
        return self.state == "upgrade-required"


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(version)
    if match is None:
        raise ValueError(f"invalid release version: {version!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("release policy updated_at must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("release policy updated_at must include a timezone")
        return parsed.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise ValueError("invalid release policy timestamp") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    decoded: dict[str, object] = {}
    for key, value in pairs:
        if key in decoded:
            raise ValueError(f"duplicate JSON key: {key}")
        decoded[key] = value
    return decoded


def _decode_json(payload: bytes) -> object:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (json.JSONDecodeError, MemoryError, RecursionError, UnicodeError) as exc:
        raise ValueError("invalid release policy JSON") from exc


def parse_release_policy(payload: bytes) -> ReleasePolicy:
    if len(payload) > MAX_POLICY_BYTES:
        raise ValueError("release policy exceeds the size limit")
    decoded = _decode_json(payload)
    if not isinstance(decoded, dict):
        raise ValueError("release policy must be a JSON object")
    expected = {
        "schema_version",
        "latest_version",
        "minimum_supported_version",
        "updated_at",
    }
    if set(decoded) != expected:
        raise ValueError("release policy fields do not match schema version 1")
    if type(decoded["schema_version"]) is not int or decoded["schema_version"] != 1:
        raise ValueError("unsupported release policy schema")
    latest = decoded["latest_version"]
    minimum = decoded["minimum_supported_version"]
    if not isinstance(latest, str) or not isinstance(minimum, str):
        raise ValueError("release policy versions must be strings")
    if _version_tuple(latest) < _version_tuple(minimum):
        raise ValueError("latest_version cannot precede minimum_supported_version")
    updated_at = decoded["updated_at"]
    _parse_timestamp(updated_at)
    return ReleasePolicy(
        schema_version=1,
        latest_version=latest,
        minimum_supported_version=minimum,
        updated_at=updated_at,
    )


def _fetch_remote_policy() -> bytes:
    request = Request(
        POLICY_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "wikibrain-version-policy",
        },
    )
    with urlopen(request, timeout=2.0) as response:
        if response.geturl() != POLICY_URL:
            raise ValueError("release policy response is not the official policy URL")
        payload = response.read(MAX_POLICY_BYTES + 1)
    if len(payload) > MAX_POLICY_BYTES:
        raise ValueError("release policy exceeds the size limit")
    return payload


def _decision(
    policy: ReleasePolicy,
    current_version: str,
    *,
    source: str,
) -> PolicyDecision:
    return PolicyDecision(
        state=(
            "upgrade-required"
            if policy.requires_upgrade(current_version)
            else "supported"
        ),
        current_version=current_version,
        minimum_supported_version=policy.minimum_supported_version,
        latest_version=policy.latest_version,
        source=source,
    )


def _unavailable(current_version: str, *, source: str) -> PolicyDecision:
    return PolicyDecision(
        state="unavailable",
        current_version=current_version,
        minimum_supported_version=None,
        latest_version=None,
        source=source,
    )


def _read_fresh_cache(
    path: Path,
    current_version: str,
    now: datetime,
) -> PolicyDecision | None:
    try:
        with path.open("rb") as cache_file:
            cache_payload = cache_file.read(MAX_CACHE_BYTES + 1)
        if len(cache_payload) > MAX_CACHE_BYTES:
            raise ValueError("release policy cache exceeds the size limit")
        cached = _decode_json(cache_payload)
        if not isinstance(cached, dict):
            raise ValueError("release policy cache must be a JSON object")
        if set(cached) != {"schema_version", "checked_at", "policy"}:
            raise ValueError("release policy cache fields do not match schema version 1")
        if (
            type(cached.get("schema_version")) is not int
            or cached["schema_version"] != 1
        ):
            raise ValueError("unsupported release policy cache schema")
        checked_at = _parse_timestamp(cached["checked_at"])
        age = now - checked_at
        if age < timedelta(0) or age >= CACHE_TTL:
            return None
        payload = cached.get("policy")
        if payload is None:
            return _unavailable(current_version, source="cache")
        policy = parse_release_policy(json.dumps(payload).encode("utf-8"))
        return _decision(policy, current_version, source="cache")
    except (KeyError, MemoryError, OSError, RecursionError, TypeError, ValueError):
        return None


def _write_cache(path: Path, now: datetime, policy: ReleasePolicy | None) -> None:
    payload = {
        "schema_version": 1,
        "checked_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "policy": asdict(policy) if policy is not None else None,
    }
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n")


def check_release_policy(
    home: Path,
    current_version: str,
    *,
    now: datetime | None = None,
    fetcher: Callable[[], bytes] | None = None,
) -> PolicyDecision:
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    cache_path = home.expanduser().resolve() / CACHE_NAME
    cached = _read_fresh_cache(cache_path, current_version, checked_at)
    if cached is not None:
        return cached

    try:
        policy = parse_release_policy((fetcher or _fetch_remote_policy)())
        decision = _decision(policy, current_version, source="remote")
    except (
        HTTPException,
        MemoryError,
        OSError,
        RecursionError,
        UnicodeError,
        ValueError,
    ):
        policy = None
        decision = _unavailable(current_version, source="remote-error")

    try:
        _write_cache(cache_path, checked_at, policy)
    except (MemoryError, OSError, RecursionError):
        pass
    return decision
