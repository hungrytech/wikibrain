from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from argparse import Namespace
from contextlib import redirect_stderr
from datetime import UTC, datetime, timedelta
from http.client import IncompleteRead
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wikibrain.cli import _enforce_minimum_supported_version, main
from wikibrain.version_policy import (
    CACHE_NAME,
    CACHE_TTL,
    MAX_CACHE_BYTES,
    POLICY_URL,
    PolicyDecision,
    _download_remote_policy,
    _fetch_remote_policy,
    _open_trusted_cache,
    _windows_cache_path_is_private,
    check_release_policy,
    parse_release_policy,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def _policy(
    *,
    latest: str = "0.1.7",
    minimum: str = "0.1.6",
    updated_at: str = "2026-07-22T12:00:00Z",
) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "latest_version": latest,
            "minimum_supported_version": minimum,
            "updated_at": updated_at,
        }
    ).encode()


class _Response:
    def __init__(self, payload: bytes, url: str) -> None:
        self.payload = payload
        self.url = url

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


class VersionPolicyTests(unittest.TestCase):
    def test_repository_policy_is_valid_and_does_not_reject_current_release(self) -> None:
        policy = parse_release_policy((ROOT / "release-policy.json").read_bytes())
        project = __import__("tomllib").loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertEqual(policy.schema_version, 1)
        self.assertEqual(policy.latest_version, project["project"]["version"])
        self.assertFalse(policy.requires_upgrade(project["project"]["version"]))
        for readme_name in (
            "README.md",
            "README.ko.md",
            "README.ja.md",
            "README.zh-CN.md",
        ):
            readme = (ROOT / readme_name).read_text(encoding="utf-8")
            self.assertIn("minimum_supported_version", readme, readme_name)
            self.assertIn(
                "brew update && brew upgrade hungrytech/tap/wikibrain",
                readme,
                readme_name,
            )
            self.assertIn(
                "pipx install --force",
                readme,
                readme_name,
            )

    def test_semver_comparison_is_numeric_not_lexicographic(self) -> None:
        policy = parse_release_policy(_policy(latest="0.10.0", minimum="0.9.9"))

        self.assertFalse(policy.requires_upgrade("0.10.0"))
        self.assertTrue(policy.requires_upgrade("0.9.8"))

    def test_oversized_policy_fails_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decision = check_release_policy(
                Path(temporary),
                "0.1.0",
                now=NOW,
                fetcher=lambda: b"{" + (b"x" * (64 * 1024)),
            )

        self.assertFalse(decision.upgrade_required)
        self.assertEqual(decision.state, "unavailable")

    def test_remote_fetch_is_get_only_and_accepts_only_the_trusted_https_host(self) -> None:
        requests = []

        def open_trusted(request: object, *, timeout: float) -> _Response:
            requests.append((request, timeout))
            return _Response(
                _policy(),
                "https://raw.githubusercontent.com/hungrytech/wikibrain/main/release-policy.json",
            )

        with patch("wikibrain.version_policy.urlopen", side_effect=open_trusted):
            self.assertEqual(_download_remote_policy(), _policy())

        request, timeout = requests[0]
        self.assertIsNone(request.data)
        self.assertEqual(timeout, 2.0)

        with patch(
            "wikibrain.version_policy.urlopen",
            return_value=_Response(_policy(), "https://example.com/policy.json"),
        ):
            with self.assertRaisesRegex(ValueError, "official policy URL"):
                _download_remote_policy()

        for redirected_url in (
            "https://raw.githubusercontent.com/attacker/repo/main/release-policy.json",
            "https://raw.githubusercontent.com/hungrytech/wikibrain/other/release-policy.json",
        ):
            with self.subTest(redirected_url=redirected_url):
                with patch(
                    "wikibrain.version_policy.urlopen",
                    return_value=_Response(_policy(), redirected_url),
                ):
                    with self.assertRaisesRegex(ValueError, "official policy URL"):
                        _download_remote_policy()

        self.assertEqual(POLICY_URL, requests[0][0].full_url)

    def test_truncated_http_body_fails_open_and_is_negatively_cached(self) -> None:
        class TruncatedResponse:
            def __enter__(self) -> TruncatedResponse:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def geturl(self) -> str:
                return POLICY_URL

            def read(self, _limit: int) -> bytes:
                raise IncompleteRead(b'{"schema_version":', 100)

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            with patch(
                "wikibrain.version_policy.urlopen",
                return_value=TruncatedResponse(),
            ):
                decision = check_release_policy(
                    home,
                    "0.1.6",
                    now=NOW,
                    fetcher=_download_remote_policy,
                )
            with patch(
                "wikibrain.version_policy.urlopen",
                side_effect=AssertionError("negative cache must avoid another request"),
            ):
                cached = check_release_policy(
                    home,
                    "0.1.6",
                    now=NOW + timedelta(minutes=1),
                )

        self.assertEqual(decision.state, "unavailable")
        self.assertEqual(decision.source, "remote-error")
        self.assertEqual(cached.state, "unavailable")
        self.assertEqual(cached.source, "cache")

    def test_remote_fetch_deadline_terminates_its_worker(self) -> None:
        started = time.monotonic()
        with patch("wikibrain.version_policy.TOTAL_FETCH_DEADLINE", 0.05):
            with self.assertRaises(TimeoutError):
                _fetch_remote_policy(child_code="import time; time.sleep(3600)")
        self.assertLess(time.monotonic() - started, 0.5)

    def test_remote_fetch_worker_start_failure_is_an_io_failure(self) -> None:
        with patch(
            "wikibrain.version_policy.subprocess.Popen",
            side_effect=RuntimeError("spawn disabled"),
        ):
            with self.assertRaisesRegex(OSError, "could not start"):
                _fetch_remote_policy()

    def test_cleanup_continues_after_lifecycle_and_stream_errors(self) -> None:
        class BrokenStream:
            def __init__(self) -> None:
                self.close_calls = 0

            def close(self) -> None:
                self.close_calls += 1
                raise RuntimeError("close failed")

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = BrokenStream()
                self.stderr = None
                self.stdin = None
                self.returncode = None
                self.running = True
                self.kill_calls = 0
                self.wait_calls = 0
                self.communicate_calls = 0

            def poll(self) -> int | None:
                return None if self.running else -9

            def kill(self) -> None:
                self.kill_calls += 1
                self.running = False

            def terminate(self) -> None:
                raise AssertionError("terminate failed")

            def wait(self, timeout: float) -> int:
                self.wait_calls += 1
                if self.running:
                    raise subprocess.TimeoutExpired("worker", timeout)
                return -9

            def communicate(self, timeout: float) -> tuple[bytes, None]:
                self.communicate_calls += 1
                if self.communicate_calls == 1:
                    raise subprocess.TimeoutExpired("worker", timeout)
                return b"", None

        process = FakeProcess()
        with patch("wikibrain.version_policy.subprocess.Popen", return_value=process):
            with patch("wikibrain.version_policy.TOTAL_FETCH_DEADLINE", 0.01):
                with self.assertRaises(TimeoutError):
                    _fetch_remote_policy()

        self.assertGreaterEqual(process.kill_calls, 1)
        self.assertGreaterEqual(process.wait_calls, 1)
        self.assertGreaterEqual(process.communicate_calls, 2)
        self.assertEqual(process.stdout.close_calls, 1)

    @unittest.skipIf(os.name == "nt", "POSIX child/FD inspection")
    def test_repeated_timeouts_leave_no_child_or_file_descriptor(self) -> None:
        def children() -> set[int]:
            result = subprocess.run(
                ["ps", "-axo", "pid=,ppid="],
                check=True,
                capture_output=True,
                text=True,
            )
            candidates = {
                int(fields[0])
                for line in result.stdout.splitlines()
                if len(fields := line.split()) == 2 and int(fields[1]) == os.getpid()
            }
            alive: set[int] = set()
            for process_id in candidates:
                try:
                    os.kill(process_id, 0)
                except ProcessLookupError:
                    continue
                alive.add(process_id)
            return alive

        before_children = children()
        before_fds = len(os.listdir("/dev/fd"))
        for _ in range(10):
            with patch("wikibrain.version_policy.TOTAL_FETCH_DEADLINE", 0.02):
                with self.assertRaises(TimeoutError):
                    _fetch_remote_policy(child_code="import time; time.sleep(3600)")
        self.assertEqual(children(), before_children)
        self.assertEqual(len(os.listdir("/dev/fd")), before_fds)

    def test_schema_rejects_bool_float_and_duplicate_keys(self) -> None:
        valid_fields = (
            '"latest_version":"0.1.7",'
            '"minimum_supported_version":"0.1.6",'
            '"updated_at":"2026-07-22T12:00:00Z"'
        )
        payloads = (
            f'{{"schema_version":true,{valid_fields}}}'.encode(),
            f'{{"schema_version":1.0,{valid_fields}}}'.encode(),
            (
                '{"schema_version":1,"schema_version":1,'
                f"{valid_fields}}}"
            ).encode(),
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_release_policy(payload)

    def test_deep_remote_json_and_oversized_or_deep_cache_fail_open(self) -> None:
        deep_json = (b"[" * 2_000) + (b"]" * 2_000)
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            decision = check_release_policy(
                home, "0.1.0", now=NOW, fetcher=lambda: deep_json
            )
            self.assertFalse(decision.upgrade_required)
            self.assertEqual(decision.state, "unavailable")

        cache_payloads = (
            b"{" + (b"x" * MAX_CACHE_BYTES),
            deep_json,
        )
        for cache_payload in cache_payloads:
            with self.subTest(size=len(cache_payload)):
                with tempfile.TemporaryDirectory() as temporary:
                    home = Path(temporary)
                    home.joinpath("release-policy-cache.json").write_bytes(cache_payload)
                    decision = check_release_policy(
                        home,
                        "0.1.0",
                        now=NOW,
                        fetcher=lambda: (_ for _ in ()).throw(OSError("offline")),
                    )
                    self.assertFalse(decision.upgrade_required)
                    self.assertEqual(decision.state, "unavailable")
                    self.assertLessEqual(
                        home.joinpath("release-policy-cache.json").stat().st_size,
                        MAX_CACHE_BYTES,
                    )

    def test_timestamp_overflow_in_remote_or_cache_fails_open(self) -> None:
        overflow_timestamp = "9999-12-31T23:59:59.999999-23:59"
        remote_payload = _policy().replace(
            b"2026-07-22T12:00:00Z", overflow_timestamp.encode()
        )
        with tempfile.TemporaryDirectory() as temporary:
            decision = check_release_policy(
                Path(temporary), "0.1.0", now=NOW, fetcher=lambda: remote_payload
            )
        self.assertEqual(decision.state, "unavailable")
        self.assertEqual(decision.source, "remote-error")

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            home.joinpath("release-policy-cache.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "checked_at": overflow_timestamp,
                        "policy": json.loads(_policy()),
                    }
                ),
                encoding="utf-8",
            )
            decision = check_release_policy(
                home,
                "0.1.0",
                now=NOW,
                fetcher=lambda: (_ for _ in ()).throw(OSError("offline")),
            )
        self.assertEqual(decision.state, "unavailable")

    def test_cache_rejects_unexpected_top_level_fields_and_refetches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            home.joinpath("release-policy-cache.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "checked_at": NOW.isoformat().replace("+00:00", "Z"),
                        "policy": json.loads(
                            _policy(latest="9.0.0", minimum="9.0.0")
                        ),
                        "unexpected": "must invalidate the cache",
                    }
                ),
                encoding="utf-8",
            )
            decision = check_release_policy(
                home,
                "0.1.6",
                now=NOW,
                fetcher=lambda: _policy(latest="0.1.6", minimum="0.1.6"),
            )

        self.assertFalse(decision.upgrade_required)
        self.assertEqual(decision.source, "remote")

    def test_cache_rejects_mismatched_current_and_last_accepted_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            home.joinpath(CACHE_NAME).write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "checked_at": NOW.isoformat().replace("+00:00", "Z"),
                        "policy": json.loads(_policy()),
                        "last_accepted_policy": json.loads(
                            _policy(latest="9.0.0", minimum="9.0.0")
                        ),
                    }
                ),
                encoding="utf-8",
            )
            decision = check_release_policy(
                home,
                "0.1.7",
                now=NOW,
                fetcher=lambda: _policy(),
            )

        self.assertEqual(decision.state, "supported")
        self.assertEqual(decision.source, "remote")

    @unittest.skipIf(os.name == "nt", "POSIX ownership and mode contract")
    def test_cache_rejects_symlinks_and_group_or_other_writable_files(self) -> None:
        poisoned = {
            "schema_version": 1,
            "checked_at": NOW.isoformat().replace("+00:00", "Z"),
            "policy": json.loads(_policy(latest="9.0.0", minimum="9.0.0")),
        }
        for attack in ("symlink", "writable"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                cache = home / "release-policy-cache.json"
                if attack == "symlink":
                    target = home / "attacker-controlled.json"
                    target.write_text(json.dumps(poisoned), encoding="utf-8")
                    cache.symlink_to(target)
                else:
                    cache.write_text(json.dumps(poisoned), encoding="utf-8")
                    cache.chmod(0o666)

                decision = check_release_policy(
                    home,
                    "0.1.7",
                    now=NOW,
                    fetcher=lambda: _policy(latest="0.1.7", minimum="0.1.7"),
                )

                self.assertEqual(decision.state, "supported")
                self.assertEqual(decision.source, "remote")

    @unittest.skipUnless(sys.platform == "darwin", "macOS extended ACL contract")
    def test_cache_rejects_a_macos_extended_acl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / CACHE_NAME
            cache.write_text("{}", encoding="utf-8")
            cache.chmod(0o600)
            subprocess.run(
                ["chmod", "+a", "everyone allow write", str(cache)],
                check=True,
            )
            with self.assertRaisesRegex(OSError, "extended ACL"):
                _open_trusted_cache(cache, cache.parent)

    def test_windows_cache_policy_requires_a_regular_file_in_user_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "profile"
            profile.mkdir()
            private_cache = profile / ".wikibrain" / "release-policy-cache.json"
            private_cache.parent.mkdir()
            private_cache.write_text("{}", encoding="utf-8")
            shared_cache = root / "shared" / "release-policy-cache.json"
            shared_cache.parent.mkdir()
            shared_cache.write_text("{}", encoding="utf-8")

            self.assertTrue(
                _windows_cache_path_is_private(private_cache, profile)
            )
            self.assertFalse(
                _windows_cache_path_is_private(shared_cache, profile)
            )
            if os.name != "nt":
                symlink_cache = profile / ".wikibrain" / "linked-cache.json"
                symlink_cache.symlink_to(shared_cache)
                self.assertFalse(
                    _windows_cache_path_is_private(symlink_cache, profile)
                )

    @unittest.skipUnless(os.name == "nt", "Windows handle and DACL contract")
    def test_windows_handle_validation_accepts_a_private_user_cache(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.home()) as temporary:
            cache = Path(temporary) / CACHE_NAME
            cache.write_bytes(b"trusted")
            with _open_trusted_cache(cache, cache.parent) as handle:
                self.assertEqual(handle.read(), b"trusted")

    @unittest.skipUnless(os.name == "nt", "Windows CRT descriptor contract")
    def test_windows_fdopen_failure_closes_the_transferred_descriptor(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.home()) as temporary:
            cache = Path(temporary) / CACHE_NAME
            cache.write_bytes(b"trusted")
            with patch(
                "wikibrain.windows_cache.os.fdopen",
                side_effect=RuntimeError("fdopen failed"),
            ), patch(
                "wikibrain.windows_cache.os.close", wraps=os.close
            ) as close_descriptor:
                with self.assertRaisesRegex(RuntimeError, "fdopen failed"):
                    _open_trusted_cache(cache, cache.parent)
            close_descriptor.assert_called_once()

    @unittest.skipUnless(os.name == "nt", "Windows custom-home contract")
    def test_windows_cache_accepts_a_private_configured_home_outside_profile(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            configured_home = Path(temporary)
            try:
                configured_home.resolve().relative_to(Path.home().resolve())
            except ValueError:
                pass
            else:
                self.skipTest("repository is inside the Windows user profile")
            account = subprocess.run(
                ["whoami"], check=True, capture_output=True, text=True
            ).stdout.strip()
            subprocess.run(
                [
                    "icacls",
                    str(configured_home),
                    "/inheritance:r",
                    "/grant:r",
                    f"{account}:(OI)(CI)F",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            cache = configured_home / CACHE_NAME
            cache.write_bytes(b"trusted")
            with _open_trusted_cache(cache, configured_home) as handle:
                self.assertEqual(handle.read(), b"trusted")

    @unittest.skipIf(os.name == "nt", "POSIX ownership contract")
    def test_cache_rejects_a_foreign_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / CACHE_NAME
            cache.write_text("{}", encoding="utf-8")
            metadata = cache.stat()
            foreign_metadata = SimpleNamespace(
                st_mode=metadata.st_mode,
                st_uid=os.getuid() + 1,
            )
            with patch(
                "wikibrain.version_policy.os.fstat",
                return_value=foreign_metadata,
            ):
                with self.assertRaisesRegex(OSError, "not owned"):
                    _open_trusted_cache(cache, cache.parent)

    def test_policy_rejects_pre_schema_epoch_and_excessive_future_timestamp(self) -> None:
        for updated_at in (
            "1970-01-01T00:00:00Z",
            "2026-07-22T12:05:01Z",
            "9999-01-01T00:00:00Z",
        ):
            with self.subTest(updated_at=updated_at):
                with self.assertRaises(ValueError):
                    parse_release_policy(_policy(updated_at=updated_at), now=NOW)

    def test_remote_policy_rollback_is_rejected_against_stale_accepted_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            accepted = check_release_policy(
                home,
                "0.1.7",
                now=NOW,
                fetcher=lambda: _policy(
                    latest="0.1.7",
                    minimum="0.1.7",
                    updated_at="2026-07-22T12:00:00Z",
                ),
            )
            rollback = check_release_policy(
                home,
                "0.1.7",
                now=NOW + CACHE_TTL + timedelta(seconds=1),
                fetcher=lambda: _policy(
                    latest="9.0.0",
                    minimum="9.0.0",
                    updated_at="2026-07-22T11:59:59Z",
                ),
            )
            negatively_cached = check_release_policy(
                home,
                "0.1.7",
                now=NOW + CACHE_TTL + timedelta(minutes=1),
                fetcher=lambda: self.fail("rollback failure must be negatively cached"),
            )
            repeated_rollback = check_release_policy(
                home,
                "0.1.7",
                now=NOW + (CACHE_TTL * 2) + timedelta(seconds=2),
                fetcher=lambda: _policy(
                    latest="10.0.0",
                    minimum="10.0.0",
                    updated_at="2026-07-22T11:00:00Z",
                ),
            )

        self.assertEqual(accepted.state, "supported")
        self.assertEqual(rollback.state, "unavailable")
        self.assertEqual(rollback.source, "remote-error")
        self.assertEqual(negatively_cached.source, "cache")
        self.assertEqual(repeated_rollback.state, "unavailable")
        self.assertEqual(repeated_rollback.source, "remote-error")

    def test_clock_regression_does_not_delete_the_rollback_floor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            future_now = NOW + timedelta(days=1)
            accepted = check_release_policy(
                home,
                "0.1.7",
                now=future_now,
                fetcher=lambda: _policy(
                    updated_at="2026-07-23T12:00:00Z",
                ),
            )
            offline_after_clock_rollback = check_release_policy(
                home,
                "0.1.7",
                now=NOW,
                fetcher=lambda: (_ for _ in ()).throw(OSError("offline")),
            )
            rejected_old_policy = check_release_policy(
                home,
                "0.1.7",
                now=future_now + CACHE_TTL + timedelta(seconds=1),
                fetcher=lambda: _policy(
                    latest="9.0.0",
                    minimum="9.0.0",
                    updated_at="2026-07-22T12:00:00Z",
                ),
            )

        self.assertEqual(accepted.state, "supported")
        self.assertEqual(offline_after_clock_rollback.state, "unavailable")
        self.assertEqual(rejected_old_policy.state, "unavailable")
        self.assertEqual(rejected_old_policy.source, "remote-error")

    def test_unexpected_runtime_fetch_failure_fails_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decision = check_release_policy(
                Path(temporary),
                "0.1.7",
                now=NOW,
                fetcher=lambda: (_ for _ in ()).throw(RuntimeError("no workers")),
            )
        self.assertEqual(decision.state, "unavailable")
        self.assertEqual(decision.source, "remote-error")

    def test_naive_now_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "timezone-aware"):
                check_release_policy(
                    Path(temporary),
                    "0.1.7",
                    now=datetime(2026, 7, 22, 12, 0),
                    fetcher=_policy,
                )

    def test_remote_policy_blocks_a_version_below_the_minimum_and_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            calls = 0

            def fetcher() -> bytes:
                nonlocal calls
                calls += 1
                return _policy()

            decision = check_release_policy(
                home, "0.1.5", now=NOW, fetcher=fetcher
            )
            cached = check_release_policy(
                home,
                "0.1.5",
                now=NOW + timedelta(minutes=5),
                fetcher=lambda: self.fail("fresh policy cache must avoid the network"),
            )

            self.assertTrue(decision.upgrade_required)
            self.assertEqual(decision.minimum_supported_version, "0.1.6")
            self.assertEqual(decision.latest_version, "0.1.7")
            self.assertEqual(decision.source, "remote")
            self.assertTrue(cached.upgrade_required)
            self.assertEqual(cached.source, "cache")
            self.assertEqual(calls, 1)
            if os.name != "nt":
                self.assertEqual(
                    home.joinpath("release-policy-cache.json").stat().st_mode & 0o777,
                    0o600,
                )

    def test_current_version_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decision = check_release_policy(
                Path(temporary), "0.1.6", now=NOW, fetcher=lambda: _policy()
            )

        self.assertFalse(decision.upgrade_required)
        self.assertEqual(decision.state, "supported")

    def test_network_failure_fails_open_and_negative_cache_avoids_hook_delay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            calls = 0

            def unavailable() -> bytes:
                nonlocal calls
                calls += 1
                raise OSError("offline")

            first = check_release_policy(
                home, "0.1.0", now=NOW, fetcher=unavailable
            )
            second = check_release_policy(
                home,
                "0.1.0",
                now=NOW + timedelta(minutes=10),
                fetcher=unavailable,
            )

            self.assertFalse(first.upgrade_required)
            self.assertEqual(first.state, "unavailable")
            self.assertEqual(second.source, "cache")
            self.assertEqual(calls, 1)

    def test_stale_negative_cache_retries_the_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            check_release_policy(
                home,
                "0.1.0",
                now=NOW,
                fetcher=lambda: (_ for _ in ()).throw(OSError("offline")),
            )
            decision = check_release_policy(
                home,
                "0.1.0",
                now=NOW + CACHE_TTL + timedelta(seconds=1),
                fetcher=lambda: _policy(),
            )

        self.assertTrue(decision.upgrade_required)
        self.assertEqual(decision.source, "remote")

    def test_future_dated_cache_is_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            home.joinpath("release-policy-cache.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "checked_at": (NOW + timedelta(days=1))
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "policy": json.loads(
                            _policy(latest="9.0.0", minimum="9.0.0")
                        ),
                    }
                ),
                encoding="utf-8",
            )
            decision = check_release_policy(
                home,
                "0.1.6",
                now=NOW,
                fetcher=lambda: _policy(latest="0.1.6", minimum="0.1.6"),
            )

        self.assertFalse(decision.upgrade_required)
        self.assertEqual(decision.source, "remote")

    def test_malformed_or_rollback_policy_fails_open(self) -> None:
        malformed = b'{"schema_version": 1}'
        rollback = _policy(latest="0.1.5", minimum="0.1.6")
        for payload in (malformed, rollback, b"not-json"):
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as temporary:
                    decision = check_release_policy(
                        Path(temporary), "0.1.0", now=NOW, fetcher=lambda: payload
                    )
                self.assertFalse(decision.upgrade_required)
                self.assertEqual(decision.state, "unavailable")

    def test_operational_command_is_blocked_with_homebrew_remediation(self) -> None:
        decision = PolicyDecision(
            state="upgrade-required",
            current_version="0.1.5",
            minimum_supported_version="0.1.6",
            latest_version="0.1.7",
            source="remote",
        )

        with self.assertRaisesRegex(RuntimeError, "brew upgrade hungrytech/tap/wikibrain"):
            _enforce_minimum_supported_version(
                Namespace(command_name="recall"),
                Path("/unused"),
                checker=lambda _home, _version: decision,
                platform_name="darwin",
            )

    def test_windows_block_uses_version_pinned_native_installer_remediation(self) -> None:
        decision = PolicyDecision(
            state="upgrade-required",
            current_version="0.1.5",
            minimum_supported_version="0.1.6",
            latest_version="0.1.7",
            source="remote",
        )

        with self.assertRaises(RuntimeError) as caught:
            _enforce_minimum_supported_version(
                Namespace(command_name="recall"),
                Path("/unused"),
                checker=lambda _home, _version: decision,
                platform_name="win32",
            )
        message = str(caught.exception)
        self.assertIn("v0.1.7/scripts/install-windows.ps1", message)
        self.assertIn(
            "pipx install --force git+https://github.com/hungrytech/wikibrain.git@v0.1.7",
            message,
        )

    def test_safety_and_remediation_commands_bypass_the_policy_check(self) -> None:
        for command in (
            "doctor",
            "status",
            "pause",
            "forget",
            "retention",
            "setup",
            "hooks",
            "skills",
        ):
            with self.subTest(command=command):
                _enforce_minimum_supported_version(
                    Namespace(command_name=command),
                    Path("/unused"),
                    checker=lambda *_: self.fail(
                        f"{command} must remain available without network access"
                    ),
                )

    def test_init_dry_run_bypasses_policy_without_writing_cache(self) -> None:
        _enforce_minimum_supported_version(
            Namespace(command_name="init", dry_run=True),
            Path("/unused"),
            checker=lambda *_: self.fail("dry-run must not perform a policy check"),
        )

    def test_init_apply_enforces_policy(self) -> None:
        decision = PolicyDecision(
            state="upgrade-required",
            current_version="0.1.5",
            minimum_supported_version="0.1.6",
            latest_version="0.1.7",
            source="remote",
        )
        with self.assertRaises(RuntimeError):
            _enforce_minimum_supported_version(
                Namespace(command_name="init", dry_run=False),
                Path("/unused"),
                checker=lambda *_: decision,
            )

    def test_main_blocks_before_loading_uninitialized_storage(self) -> None:
        decision = PolicyDecision(
            state="upgrade-required",
            current_version="0.1.5",
            minimum_supported_version="0.1.6",
            latest_version="0.1.7",
            source="cache",
        )
        stderr = StringIO()
        with patch("wikibrain.cli.check_release_policy", return_value=decision):
            with redirect_stderr(stderr):
                result = main(["recall", "anything"])

        self.assertEqual(result, 1)
        self.assertIn("minimum supported version is 0.1.6", stderr.getvalue())
        self.assertNotIn("not initialized", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
