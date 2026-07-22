from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr
from datetime import UTC, datetime, timedelta
from http.client import IncompleteRead
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from wikibrain.cli import _enforce_minimum_supported_version, main
from wikibrain.version_policy import (
    CACHE_TTL,
    MAX_CACHE_BYTES,
    POLICY_URL,
    PolicyDecision,
    _fetch_remote_policy,
    check_release_policy,
    parse_release_policy,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def _policy(*, latest: str = "0.1.7", minimum: str = "0.1.6") -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "latest_version": latest,
            "minimum_supported_version": minimum,
            "updated_at": "2026-07-22T12:00:00Z",
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
            self.assertEqual(_fetch_remote_policy(), _policy())

        request, timeout = requests[0]
        self.assertIsNone(request.data)
        self.assertEqual(timeout, 2.0)

        with patch(
            "wikibrain.version_policy.urlopen",
            return_value=_Response(_policy(), "https://example.com/policy.json"),
        ):
            with self.assertRaisesRegex(ValueError, "official policy URL"):
                _fetch_remote_policy()

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
                        _fetch_remote_policy()

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
                decision = check_release_policy(home, "0.1.6", now=NOW)
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
