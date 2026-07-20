from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wikibrain.config import BrainConfig
from wikibrain.curation import Curator
from wikibrain.hook_adapters import normalize_hook
from wikibrain.hooks import process_hook, run_hook_command
from wikibrain.storage import BrainStore


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
FAKE_WIKIMAP = FIXTURES / "fake_wikimap.py"


def fixture(provider: str, name: str) -> dict:
    path = FIXTURES / "hooks" / provider / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class HookContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.config = BrainConfig.create(
            self.root / "brain",
            self.root / "brain" / "vault",
            [self.workspace],
        )
        self.config.wikimap_command = str(FAKE_WIKIMAP)
        self.config.save()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def with_workspace(self, payload: dict) -> dict:
        updated = dict(payload)
        updated["cwd"] = str(self.workspace)
        return updated

    def test_all_provider_event_fixtures_normalize(self) -> None:
        names = ("session_start", "user_prompt", "post_tool", "stop", "post_compact")
        expected = (
            "SessionStart",
            "UserPromptSubmit",
            "PostToolUse",
            "Stop",
            "PostCompact",
        )
        for provider in ("claude", "codex"):
            for fixture_name, event_name in zip(names, expected, strict=True):
                with self.subTest(provider=provider, event=event_name):
                    event = normalize_hook(provider, fixture(provider, fixture_name))
                    self.assertEqual(event.name, event_name)
        codex_compact = normalize_hook("codex", fixture("codex", "post_compact"))
        self.assertIsNone(codex_compact.compact_summary)
        claude_compact = normalize_hook("claude", fixture("claude", "post_compact"))
        self.assertIn("Atlas", claude_compact.compact_summary or "")

    def test_claude_turn_is_recalled_by_new_codex_session(self) -> None:
        prompt = self.with_workspace(fixture("claude", "user_prompt"))
        stop = self.with_workspace(fixture("claude", "stop"))
        process_hook("claude", prompt, self.config)
        stop_output, stop_result = process_hook("claude", stop, self.config)
        self.assertEqual(stop_output, {})
        self.assertTrue(stop_result.captured)

        start = self.with_workspace(fixture("codex", "session_start"))
        output, result = process_hook("codex", start, self.config)
        self.assertIn("Project Atlas uses port 6432", result.context)
        self.assertEqual(
            output["hookSpecificOutput"]["hookEventName"], "SessionStart"
        )
        self.assertIn("<memory-data>", output["hookSpecificOutput"]["additionalContext"])
        self.assertIn('id="turn-', output["hookSpecificOutput"]["additionalContext"])

    def test_codex_turn_is_recalled_by_new_claude_session(self) -> None:
        prompt = self.with_workspace(fixture("codex", "user_prompt"))
        stop = self.with_workspace(fixture("codex", "stop"))
        process_hook("codex", prompt, self.config)
        output, _ = process_hook("codex", stop, self.config)
        self.assertEqual(output, {})

        start = self.with_workspace(fixture("claude", "session_start"))
        output, result = process_hook("claude", start, self.config)
        self.assertIn("Project Borealis uses SQLite WAL", result.context)
        self.assertEqual(
            output["hookSpecificOutput"]["hookEventName"], "SessionStart"
        )

    def test_outside_allowlist_and_pause_capture_nothing(self) -> None:
        outside = fixture("codex", "user_prompt")
        outside["cwd"] = str(self.root / "outside")
        _, result = process_hook("codex", outside, self.config)
        self.assertFalse(result.captured)
        self.assertEqual(BrainStore(self.config.database_path).counts()["events"], 0)

        self.config.paused = True
        allowed = self.with_workspace(fixture("codex", "user_prompt"))
        _, result = process_hook("codex", allowed, self.config)
        self.assertFalse(result.captured)
        self.assertEqual(BrainStore(self.config.database_path).counts()["events"], 0)

    def test_tool_response_is_not_persisted(self) -> None:
        payload = self.with_workspace(fixture("claude", "post_tool"))
        process_hook("claude", payload, self.config)
        with BrainStore(self.config.database_path).connect() as connection:
            pointer = connection.execute(
                "SELECT pointer_json FROM tool_pointers"
            ).fetchone()[0]
            event = connection.execute(
                "SELECT metadata_json FROM events"
            ).fetchone()[0]
        self.assertNotIn("full file content", pointer)
        self.assertNotIn("full file content", event)
        self.assertNotIn("must-not-be-stored", pointer)

    def test_shell_command_is_not_persisted_as_a_tool_pointer(self) -> None:
        secret = "shell-secret-that-must-not-survive"
        payload = {
            "session_id": "shell-pointer",
            "turn_id": "shell-pointer-1",
            "cwd": str(self.workspace),
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "shell-tool-1",
            "tool_input": {
                "cmd": f"docker login -p {secret} registry.example",
                "workdir": str(self.workspace),
            },
            "tool_response": "login complete",
        }
        process_hook("codex", payload, self.config)
        with BrainStore(self.config.database_path).connect() as connection:
            pointer = connection.execute(
                "SELECT pointer_json FROM tool_pointers"
            ).fetchone()[0]
        self.assertNotIn("cmd", pointer)
        self.assertNotIn(secret, pointer)
        self.assertIn("workdir", pointer)

    def test_secrets_never_reach_database_vault_or_log(self) -> None:
        token = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"
        prompt = {
            "session_id": "secret-session",
            "turn_id": "secret-turn",
            "cwd": str(self.workspace),
            "hook_event_name": "UserPromptSubmit",
            "prompt": f"Use credential {token} for this temporary check.",
        }
        stop = {
            "session_id": "secret-session",
            "turn_id": "secret-turn",
            "cwd": str(self.workspace),
            "hook_event_name": "Stop",
            "last_assistant_message": f"The temporary credential was {token}.",
        }
        process_hook("codex", prompt, self.config)
        process_hook("codex", stop, self.config)
        for path in self.config.home_path.rglob("*"):
            if path.is_file():
                with self.subTest(path=path):
                    self.assertNotIn(token.encode(), path.read_bytes())

    def test_structured_and_service_secrets_never_reach_brain_files(self) -> None:
        secrets = [
            "discord-json-secret-123456",
            "aws-yaml-secret-654321",
            (
                "github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "0123456789abcdefghijklmnopqrstuv"
            ),
            "hf_abcdefghijklmnopqrstuvwxyz1234567890",
            "AIza" + ("A" * 35),
            "encrypted-key-material-884422",
        ]
        body = "\n".join(
            [
                f'{{"DISCORD_BOT_TOKEN":"{secrets[0]}"}}',
                f"AWS_SECRET_ACCESS_KEY: {secrets[1]}",
                secrets[2],
                secrets[3],
                secrets[4],
                (
                    "-----BEGIN ENCRYPTED PRIVATE KEY-----\n"
                    f"{secrets[5]}\n"
                    "-----END ENCRYPTED PRIVATE KEY-----"
                ),
            ]
        )
        process_hook(
            "claude",
            {
                "session_id": "structured-secret-session",
                "cwd": str(self.workspace),
                "hook_event_name": "UserPromptSubmit",
                "prompt": body,
            },
            self.config,
        )
        process_hook(
            "claude",
            {
                "session_id": "structured-secret-session",
                "cwd": str(self.workspace),
                "hook_event_name": "Stop",
                "last_assistant_message": body,
            },
            self.config,
        )
        for path in self.config.home_path.rglob("*"):
            if not path.is_file():
                continue
            data = path.read_bytes()
            for secret in secrets:
                with self.subTest(path=path, secret=secret[:12]):
                    self.assertNotIn(secret.encode(), data)

    def test_invalid_hook_input_is_valid_empty_json_and_exit_zero(self) -> None:
        stdout = io.StringIO()
        code = run_hook_command(
            "codex",
            home=self.config.home_path,
            stdin=io.BytesIO(b"not-json"),
            stdout=stdout,
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {})

    def test_fail_open_stop_is_recovered_by_the_next_session_start(self) -> None:
        prompt_payload = {
            "session_id": "outbox-turn",
            "cwd": str(self.workspace),
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Persistent outbox marker is Jade-741.",
        }
        stop_payload = {
            "session_id": "outbox-turn",
            "cwd": str(self.workspace),
            "hook_event_name": "Stop",
            "last_assistant_message": "Confirmed Jade-741.",
        }
        for payload in (prompt_payload,):
            stdout = io.StringIO()
            self.assertEqual(
                run_hook_command(
                    "claude",
                    home=self.config.home_path,
                    stdin=io.BytesIO(json.dumps(payload).encode()),
                    stdout=stdout,
                ),
                0,
            )
        with patch.object(
            Curator, "archive_turn", side_effect=OSError("injected archive failure")
        ):
            stdout = io.StringIO()
            self.assertEqual(
                run_hook_command(
                    "claude",
                    home=self.config.home_path,
                    stdin=io.BytesIO(json.dumps(stop_payload).encode()),
                    stdout=stdout,
                ),
                0,
            )
            self.assertEqual(json.loads(stdout.getvalue()), {})
        store = BrainStore(self.config.database_path)
        self.assertEqual(len(store.pending_completed_turns()), 1)

        with patch.object(
            Curator, "archive_turn", side_effect=OSError("still poisoned")
        ):
            stdout = io.StringIO()
            unrelated_start = {
                "session_id": "outbox-unrelated",
                "cwd": str(self.workspace),
                "hook_event_name": "SessionStart",
                "source": "startup",
            }
            self.assertEqual(
                run_hook_command(
                    "codex",
                    home=self.config.home_path,
                    stdin=io.BytesIO(json.dumps(unrelated_start).encode()),
                    stdout=stdout,
                ),
                0,
            )
            self.assertEqual(json.loads(stdout.getvalue()), {})
        self.assertEqual(len(store.pending_completed_turns()), 1)

        stdout = io.StringIO()
        start = {
            "session_id": "outbox-fresh",
            "cwd": str(self.workspace),
            "hook_event_name": "SessionStart",
            "source": "startup",
        }
        with patch.object(
            Curator,
            "update_index",
            side_effect=AssertionError("fast hook must not update Wikimap"),
        ):
            self.assertEqual(
                run_hook_command(
                    "codex",
                    home=self.config.home_path,
                    stdin=io.BytesIO(json.dumps(start).encode()),
                    stdout=stdout,
                ),
                0,
            )
        context = json.loads(stdout.getvalue())["hookSpecificOutput"][
            "additionalContext"
        ]
        self.assertIn("Jade-741", context)
        self.assertEqual(store.pending_completed_turns(), [])

    def test_fail_open_post_compact_summary_is_recovered_from_outbox(self) -> None:
        compact = {
            "session_id": "compact-outbox",
            "cwd": str(self.workspace),
            "hook_event_name": "PostCompact",
            "trigger": "auto",
            "compact_summary": "Compaction marker is Pearl-663.",
        }
        with patch.object(
            Curator, "archive_handoff", side_effect=OSError("injected archive failure")
        ):
            stdout = io.StringIO()
            self.assertEqual(
                run_hook_command(
                    "claude",
                    home=self.config.home_path,
                    stdin=io.BytesIO(json.dumps(compact).encode()),
                    stdout=stdout,
                ),
                0,
            )
            self.assertEqual(json.loads(stdout.getvalue()), {})
        store = BrainStore(self.config.database_path)
        pending = store.pending_handoffs()
        self.assertEqual(len(pending), 1)
        self.assertIn("Pearl-663", pending[0]["summary"])

        stdout = io.StringIO()
        start = {
            "session_id": "compact-fresh",
            "cwd": str(self.workspace),
            "hook_event_name": "SessionStart",
            "source": "startup",
        }
        self.assertEqual(
            run_hook_command(
                "codex",
                home=self.config.home_path,
                stdin=io.BytesIO(json.dumps(start).encode()),
                stdout=stdout,
            ),
            0,
        )
        context = json.loads(stdout.getvalue())["hookSpecificOutput"][
            "additionalContext"
        ]
        self.assertIn("Pearl-663", context)
        self.assertEqual(store.pending_handoffs(), [])


if __name__ == "__main__":
    unittest.main()
