from __future__ import annotations

import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from http.client import HTTPException
from pathlib import Path
from typing import BinaryIO, Callable
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
SOCKET_TIMEOUT = 2.0
FETCH_REQUEST_DEADLINE = 2.0
FETCH_CLEANUP_RESERVE = 0.5
TOTAL_FETCH_DEADLINE = 2.5
_REAL_POPEN = subprocess.Popen
MAX_FUTURE_SKEW = timedelta(minutes=5)
POLICY_SCHEMA_EPOCH = datetime(2026, 7, 22, tzinfo=UTC)
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


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    checked_at: datetime
    policy: ReleasePolicy | None
    last_accepted_policy: ReleasePolicy | None


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


def parse_release_policy(
    payload: bytes,
    *,
    now: datetime | None = None,
    allow_future: bool = False,
) -> ReleasePolicy:
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
    policy_time = _parse_timestamp(updated_at)
    reference_time = now or datetime.now(UTC)
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("release policy time must be timezone-aware")
    reference_time = reference_time.astimezone(UTC)
    if policy_time < POLICY_SCHEMA_EPOCH:
        raise ValueError("release policy predates schema version 1")
    if not allow_future and policy_time > reference_time + MAX_FUTURE_SKEW:
        raise ValueError("release policy timestamp is too far in the future")
    return ReleasePolicy(
        schema_version=1,
        latest_version=latest,
        minimum_supported_version=minimum,
        updated_at=updated_at,
    )


def _download_remote_policy() -> bytes:
    request = Request(
        POLICY_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "wikibrain-version-policy",
        },
    )
    with urlopen(request, timeout=SOCKET_TIMEOUT) as response:
        if response.geturl() != POLICY_URL:
            raise ValueError("release policy response is not the official policy URL")
        payload = response.read(MAX_POLICY_BYTES + 1)
    if len(payload) > MAX_POLICY_BYTES:
        raise ValueError("release policy exceeds the size limit")
    return payload


def _default_fetch_child_code() -> str:
    source_root = str(Path(__file__).resolve().parent.parent)
    return (
        "import os,sys,threading;"
        f"_t=threading.Timer({FETCH_REQUEST_DEADLINE!r},lambda:os._exit(124));"
        "_t.daemon=True;_t.start();"
        f"sys.path.insert(0, {source_root!r});"
        "from wikibrain.version_policy import _download_remote_policy;"
        "sys.stdout.buffer.write(_download_remote_policy())"
    )


def _process_is_running(process: subprocess.Popen[bytes]) -> bool:
    try:
        return process.poll() is None
    except BaseException:
        return True


def _set_native_returncode(process: subprocess.Popen[bytes], status: int) -> None:
    try:
        process.returncode = os.waitstatus_to_exitcode(status)
    except (AttributeError, ValueError):
        process.returncode = -signal.SIGKILL


def _native_terminate_and_reap(
    process: subprocess.Popen[bytes], deadline: float
) -> bool:
    if os.name == "posix":
        try:
            waited_pid, status = os.waitpid(process.pid, os.WNOHANG)
        except ChildProcessError:
            return True
        except OSError:
            return False
        if waited_pid == process.pid:
            _set_native_returncode(process, status)
            return True
        try:
            os.kill(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            return False
        while True:
            try:
                waited_pid, status = os.waitpid(process.pid, os.WNOHANG)
            except ChildProcessError:
                return True
            except OSError:
                return False
            if waited_pid == process.pid:
                _set_native_returncode(process, status)
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # SIGKILL has been delivered to our own child. A blocking wait here
                # is the final no-orphan guarantee, not another network allowance.
                try:
                    waited_pid, status = os.waitpid(process.pid, 0)
                except ChildProcessError:
                    return True
                except OSError:
                    return False
                _set_native_returncode(process, status)
                return waited_pid == process.pid
            time.sleep(min(0.005, remaining))

    if os.name == "nt":
        try:
            import _winapi

            handle = process._handle  # type: ignore[attr-defined]
            state = _winapi.WaitForSingleObject(handle, 0)
            if state == _winapi.WAIT_TIMEOUT:
                _winapi.TerminateProcess(handle, 1)
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                state = _winapi.WaitForSingleObject(handle, remaining_ms)
                if state == _winapi.WAIT_TIMEOUT:
                    state = _winapi.WaitForSingleObject(handle, _winapi.INFINITE)
            if state != _winapi.WAIT_OBJECT_0:
                return False
            process.returncode = _winapi.GetExitCodeProcess(handle)
            return True
        except (AttributeError, OSError):
            return False

    return False


def _generic_terminate_and_reap(
    process: subprocess.Popen[bytes], deadline: float
) -> bool:
    # This path supports test doubles and uncommon runtimes. Each operation remains
    # independent, but every wait uses only the absolute cleanup budget.
    for method_name in ("kill", "terminate", "kill"):
        if not _process_is_running(process):
            return True
        try:
            getattr(process, method_name)()
        except BaseException:
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            process.wait(timeout=remaining)
        except BaseException:
            pass
    return not _process_is_running(process)


def _cleanup_fetch_process(
    process: subprocess.Popen[bytes], deadline: float
) -> bool:
    if isinstance(process, _REAL_POPEN):
        reaped = _native_terminate_and_reap(process, deadline)
    else:
        reaped = _generic_terminate_and_reap(process, deadline)
    for stream_name in ("stdout", "stderr", "stdin"):
        try:
            stream = getattr(process, stream_name)
        except BaseException:
            continue
        if stream is not None:
            try:
                stream.close()
            except BaseException:
                pass
    return reaped


def _fetch_remote_policy(*, child_code: str | None = None) -> bytes:
    started = time.monotonic()
    cleanup_budget = min(FETCH_CLEANUP_RESERVE, TOTAL_FETCH_DEADLINE / 5)
    absolute_deadline = started + TOTAL_FETCH_DEADLINE
    request_deadline = min(
        started + FETCH_REQUEST_DEADLINE,
        absolute_deadline - cleanup_budget,
    )
    creation_flags = 0
    if os.name == "nt":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", child_code or _default_fetch_child_code()],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creation_flags,
        )
    except Exception as exc:
        raise OSError("could not start release policy worker") from exc

    result: bytes | None = None
    failure: BaseException | None = None
    try:
        remaining = request_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("release policy request exceeded its total deadline")
        try:
            stdout, _ = process.communicate(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                "release policy request exceeded its total deadline"
            ) from exc
        if process.returncode != 0:
            raise OSError("release policy worker exited without a result")
        if len(stdout) > MAX_POLICY_BYTES:
            raise ValueError("release policy response is too large")
        result = stdout
    except BaseException as exc:
        failure = exc

    reaped = _cleanup_fetch_process(process, absolute_deadline)
    if not reaped:
        raise OSError("release policy worker cleanup could not be verified") from failure
    if failure is not None:
        raise failure.with_traceback(failure.__traceback__)
    assert result is not None
    return result


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


def _fd_has_extended_acl(descriptor: int) -> bool:
    if sys.platform == "darwin":
        import ctypes
        import errno

        libc = ctypes.CDLL(None, use_errno=True)
        acl_get_fd_np = libc.acl_get_fd_np
        acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
        acl_get_fd_np.restype = ctypes.c_void_p
        acl_free = libc.acl_free
        acl_free.argtypes = [ctypes.c_void_p]
        acl_free.restype = ctypes.c_int
        ctypes.set_errno(0)
        acl = acl_get_fd_np(descriptor, 0x00000100)  # ACL_TYPE_EXTENDED
        if not acl:
            error = ctypes.get_errno()
            if error == errno.ENOENT:
                return False
            raise OSError(error, os.strerror(error))
        if acl_free(acl) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return True

    list_xattrs = getattr(os, "listxattr", None)
    if list_xattrs is None:
        raise OSError("descriptor ACL inspection is unavailable")
    acl_markers = {
        "system.posix_acl_access",
        "system.nfs4_acl",
        "security.nfs4_acl",
        "trusted.nfs4_acl",
        "system.richacl",
        "trusted.sgi_acl_file",
    }
    names = (
        name.decode("ascii", errors="ignore") if isinstance(name, bytes) else name
        for name in list_xattrs(descriptor)
    )
    return any(name.lower() in acl_markers for name in names)


def _open_trusted_cache(path: Path, trusted_home: Path) -> BinaryIO:
    if os.name == "nt":
        from wikibrain.windows_cache import open_trusted_windows_cache

        return open_trusted_windows_cache(path, trusted_home)

    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("release policy cache is not a regular file")
        if metadata.st_uid != os.getuid():
            raise OSError("release policy cache is not owned by the current user")
        if metadata.st_mode & 0o022:
            raise OSError("release policy cache is writable by group or others")
        if _fd_has_extended_acl(descriptor):
            raise OSError("release policy cache has an extended ACL")
        return os.fdopen(descriptor, "rb")
    except Exception:
        os.close(descriptor)
        raise


def _read_cache(path: Path, trusted_home: Path, now: datetime) -> _CacheEntry | None:
    try:
        with _open_trusted_cache(path, trusted_home) as cache_file:
            cache_payload = cache_file.read(MAX_CACHE_BYTES + 1)
        if len(cache_payload) > MAX_CACHE_BYTES:
            raise ValueError("release policy cache exceeds the size limit")
        cached = _decode_json(cache_payload)
        if not isinstance(cached, dict):
            raise ValueError("release policy cache must be a JSON object")
        schema_version = cached.get("schema_version")
        if type(schema_version) is not int or schema_version not in {1, 2}:
            raise ValueError("unsupported release policy cache schema")
        expected = (
            {"schema_version", "checked_at", "policy"}
            if schema_version == 1
            else {
                "schema_version",
                "checked_at",
                "policy",
                "last_accepted_policy",
            }
        )
        if set(cached) != expected:
            raise ValueError("release policy cache fields do not match its schema")
        checked_at = _parse_timestamp(cached["checked_at"])

        def decode_policy(value: object) -> ReleasePolicy | None:
            if value is None:
                return None
            return parse_release_policy(
                json.dumps(value).encode("utf-8"),
                now=now,
                allow_future=True,
            )

        policy = decode_policy(cached.get("policy"))
        last_accepted = (
            decode_policy(cached.get("last_accepted_policy"))
            if schema_version == 2
            else policy
        )
        if policy is not None and policy != last_accepted:
            raise ValueError("cached policy must match last accepted policy")
        return _CacheEntry(
            checked_at=checked_at,
            policy=policy,
            last_accepted_policy=last_accepted,
        )
    except (KeyError, MemoryError, OSError, RecursionError, TypeError, ValueError):
        return None


def _write_cache(
    path: Path,
    now: datetime,
    policy: ReleasePolicy | None,
    last_accepted_policy: ReleasePolicy | None,
) -> None:
    payload = {
        "schema_version": 2,
        "checked_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "policy": asdict(policy) if policy is not None else None,
        "last_accepted_policy": (
            asdict(last_accepted_policy) if last_accepted_policy is not None else None
        ),
    }
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n")


def check_release_policy(
    home: Path,
    current_version: str,
    *,
    now: datetime | None = None,
    fetcher: Callable[[], bytes] | None = None,
) -> PolicyDecision:
    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("release policy check time must be timezone-aware")
    checked_at = checked_at.astimezone(UTC)
    trusted_home = home.expanduser().resolve()
    cache_path = trusted_home / CACHE_NAME
    cached = _read_cache(cache_path, trusted_home, checked_at)
    if cached is not None:
        age = checked_at - cached.checked_at
        if timedelta(0) <= age < CACHE_TTL:
            if cached.policy is None:
                return _unavailable(current_version, source="cache")
            return _decision(cached.policy, current_version, source="cache")

    previous_policy = cached.last_accepted_policy if cached is not None else None
    try:
        policy = parse_release_policy(
            (fetcher or _fetch_remote_policy)(),
            now=checked_at,
        )
        if previous_policy is not None and _parse_timestamp(
            policy.updated_at
        ) < _parse_timestamp(previous_policy.updated_at):
            raise ValueError("release policy rollback detected")
        decision = _decision(policy, current_version, source="remote")
        last_accepted_policy = policy
    except (
        HTTPException,
        MemoryError,
        OSError,
        RecursionError,
        RuntimeError,
        subprocess.SubprocessError,
        UnicodeError,
        ValueError,
    ):
        policy = None
        last_accepted_policy = previous_policy
        decision = _unavailable(current_version, source="remote-error")

    try:
        _write_cache(cache_path, checked_at, policy, last_accepted_policy)
    except (MemoryError, OSError, RecursionError):
        pass
    return decision
