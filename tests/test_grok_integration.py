from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from wikibrain.cli import build_parser, command_hooks, command_status
from wikibrain.config import BrainConfig
from wikibrain.curation import Curator
from wikibrain.hook_adapters import normalize_hook
from wikibrain.hooks import _effective_provider, process_hook
from wikibrain.installer import EVENTS, _is_owned_handler, install_hooks
from wikibrain.skill_installer import default_skill_targets, install_skills
from wikibrain.storage import BrainStore
from wikibrain.wikimap_adapter import WikimapAdapter


class GrokIntegrationTests(unittest.TestCase):
    def test_normalizes_observed_native_grok_prompt_and_stop_payloads(self) -> None:
        prompt = normalize_hook(
            "grok",
            {
                "hookEventName": "user_prompt_submit",
                "sessionId": "019f-session",
                "cwd": "/tmp/project",
                "workspaceRoot": "/tmp/project/",
                "timestamp": "2026-07-22T09:43:42.691347+00:00",
                "promptId": "90f5-prompt",
                "prompt": "<user_query>\nRemember Azure-472\n</user_query>",
            },
        )
        stop = normalize_hook(
            "grok",
            {
                "hookEventName": "stop",
                "sessionId": "019f-session",
                "cwd": "/tmp/project",
                "workspaceRoot": "/tmp/project/",
                "timestamp": "2026-07-22T09:43:42.861388+00:00",
                "transcriptPath": "/tmp/.grok/sessions/updates.jsonl",
                "promptId": "90f5-prompt",
                "reason": "error",
            },
        )

        self.assertEqual(prompt.name, "UserPromptSubmit")
        self.assertEqual(prompt.turn_id, "90f5-prompt")
        self.assertIn("Azure-472", prompt.prompt or "")
        self.assertEqual(prompt.raw_metadata["prompt_id"], "90f5-prompt")
        self.assertEqual(stop.name, "Stop")
        self.assertEqual(stop.turn_id, "90f5-prompt")
        self.assertIsNone(stop.assistant_message)
        self.assertEqual(stop.raw_metadata["reason"], "error")
        self.assertEqual(
            stop.raw_metadata["transcript_path"],
            "/tmp/.grok/sessions/updates.jsonl",
        )

    def test_normalizes_native_grok_camel_case_payload(self) -> None:
        event = normalize_hook(
            "grok",
            {
                "hookEventName": "PostToolUse",
                "sessionId": "grok-session",
                "turnId": "turn-7",
                "cwd": "/tmp/project",
                "workspaceRoot": "/tmp/project",
                "toolName": "Edit",
                "toolUseId": "tool-9",
                "toolInput": {"filePath": "/tmp/project/app.py"},
                "model": "grok-build",
            },
        )

        self.assertEqual(event.provider, "grok")
        self.assertEqual(event.name, "PostToolUse")
        self.assertEqual(event.session_id, "grok-session")
        self.assertEqual(event.turn_id, "turn-7")
        self.assertEqual(event.tool_name, "Edit")
        self.assertEqual(event.tool_use_id, "tool-9")
        self.assertEqual(event.tool_pointer, {"file_path": "/tmp/project/app.py"})
        self.assertEqual(event.raw_metadata["workspace_root"], "/tmp/project")

    def test_grok_environment_overrides_claude_compatibility_provider(self) -> None:
        self.assertEqual(
            _effective_provider(
                "claude",
                {
                    "GROK_HOOK_EVENT": "UserPromptSubmit",
                    "GROK_SESSION_ID": "grok-session",
                },
            ),
            "grok",
        )
        self.assertEqual(_effective_provider("claude", {}), "claude")
        self.assertEqual(_effective_provider("grok", {}), "grok")

    def test_grok_passive_hook_captures_without_false_context_injection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            config = BrainConfig.create(root / "brain", root / "vault", [workspace])
            store = BrainStore(config.database_path)
            store.initialize()
            Curator(
                config,
                store,
                WikimapAdapter(config.vault_path, config.wikimap_command),
            ).remember(
                "The refactor uses a durable cobalt protocol.",
                title="Cobalt protocol",
                workspace=str(workspace),
                update_index=False,
            )

            output, result = process_hook(
                "grok",
                {
                    "hookEventName": "UserPromptSubmit",
                    "sessionId": "grok-session",
                    "cwd": str(workspace),
                    "prompt": "continue the refactor",
                },
                config,
            )

            self.assertEqual(output, {})
            self.assertTrue(result.captured)
            with BrainStore(config.database_path).connect() as connection:
                usage_count = connection.execute(
                    "SELECT COUNT(*) FROM document_usage"
                ).fetchone()[0]
            self.assertEqual(usage_count, 0)

    def test_observed_grok_prompt_and_stop_archive_the_same_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            config = BrainConfig.create(root / "brain", root / "vault", [workspace])
            BrainStore(config.database_path).initialize()
            common = {
                "sessionId": "019f-session",
                "cwd": str(workspace),
                "workspaceRoot": f"{workspace}/",
                "promptId": "90f5-prompt",
            }

            prompt_output, prompt_result = process_hook(
                "grok",
                {
                    **common,
                    "hookEventName": "user_prompt_submit",
                    "timestamp": "2026-07-22T09:43:42.691347+00:00",
                    "prompt": "<user_query>\nRemember Azure-472\n</user_query>",
                },
                config,
            )
            stop_output, stop_result = process_hook(
                "grok",
                {
                    **common,
                    "hookEventName": "stop",
                    "timestamp": "2026-07-22T09:43:42.861388+00:00",
                    "transcriptPath": str(root / "updates.jsonl"),
                    "reason": "error",
                },
                config,
            )

            self.assertEqual(prompt_output, {})
            self.assertEqual(stop_output, {})
            self.assertTrue(prompt_result.captured)
            self.assertTrue(stop_result.captured)
            archived = "\n".join(
                path.read_text(encoding="utf-8")
                for path in config.vault_path.rglob("*.md")
            )
            self.assertIn("Azure-472", archived)
            self.assertIn("assistant message unavailable", archived)
            self.assertIn('provider: "grok"', archived)

    def test_installs_native_grok_hooks_without_overwriting_other_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = BrainConfig.create(root / "brain", root / "vault", [root])
            hooks_path = root / ".grok" / "hooks" / "wikibrain.json"
            hooks_path.parent.mkdir(parents=True)
            hooks_path.write_text(json.dumps({"custom": {"keep": True}}), encoding="utf-8")

            first = install_hooks(
                config,
                ["grok"],
                command="/opt/homebrew/bin/brainctl",
                paths={"grok": hooks_path},
            )
            second = install_hooks(
                config,
                ["grok"],
                command="/opt/homebrew/bin/brainctl",
                paths={"grok": hooks_path},
            )

            self.assertEqual(first[0]["changes"], len(EVENTS))
            self.assertEqual(second[0]["changes"], 0)
            payload = json.loads(hooks_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["custom"], {"keep": True})
            self.assertNotIn("matcher", payload["hooks"]["SessionStart"][0])
            self.assertNotIn("matcher", payload["hooks"]["PostToolUse"][0])
            self.assertNotIn("matcher", payload["hooks"]["PostCompact"][0])
            owned = [
                handler
                for event in EVENTS
                for group in payload["hooks"][event]
                for handler in group.get("hooks", [])
                if _is_owned_handler(handler, "grok")
            ]
            self.assertEqual(len(owned), len(EVENTS))

    def test_grok_home_and_skill_target_are_supported(self) -> None:
        with patch.dict("os.environ", {"GROK_HOME": "/tmp/custom-grok-home"}):
            targets = default_skill_targets(["grok"])
        self.assertEqual(
            targets["grok"], Path("/tmp/custom-grok-home/skills/wikibrain")
        )

    def test_status_reports_an_installed_native_grok_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = BrainConfig.create(root / "brain", root / "vault", [root])
            BrainStore(config.database_path).initialize()
            grok_home = root / ".grok"
            with patch.dict("os.environ", {"GROK_HOME": str(grok_home)}):
                install_skills(["grok"])
                output = io.StringIO()
                with (
                    patch.object(WikimapAdapter, "version", return_value="1.1.0"),
                    redirect_stdout(output),
                ):
                    command_status(argparse.Namespace(json=True), config.home_path)

            skills = {
                item["client"]: item
                for item in json.loads(output.getvalue())["skills"]
            }
            self.assertEqual(set(skills), {"claude", "agents", "grok"})
            self.assertTrue(skills["grok"]["installed"])
            self.assertTrue(skills["grok"]["managed"])

    def test_hooks_status_respects_selected_clients(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [
                "--claude-settings",
                str(root / "claude.json"),
                "--codex-hooks",
                str(root / "codex.json"),
                "--grok-hooks",
                str(root / "grok.json"),
                "--json",
            ]
            scenarios = (
                (["hooks", "status", *paths], {"claude", "codex"}),
                (["hooks", "status", "--clients", "grok", *paths], {"grok"}),
            )
            for arguments, expected in scenarios:
                with self.subTest(arguments=arguments):
                    args = parser.parse_args(arguments)
                    output = io.StringIO()
                    with redirect_stdout(output):
                        command_hooks(args, root / "brain")
                    clients = {
                        item["client"] for item in json.loads(output.getvalue())
                    }
                    self.assertEqual(clients, expected)

    def test_clients_are_deduplicated_in_input_order(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["hooks", "status", "--clients", "grok,claude,grok"]
        )

        self.assertEqual(args.clients, ["grok", "claude"])

    def test_hooks_status_rejects_an_empty_client_list(self) -> None:
        parser = build_parser()
        for value in ("", ","):
            with self.subTest(value=value):
                with redirect_stderr(io.StringIO()), self.assertRaises(
                    SystemExit
                ) as raised:
                    parser.parse_args(["hooks", "status", "--clients", value])
                self.assertEqual(raised.exception.code, 2)

    def test_cli_accepts_grok_client_and_provider(self) -> None:
        parser = build_parser()
        init = parser.parse_args(["init", "--clients", "grok"])
        hook = parser.parse_args(["hook", "--provider", "grok"])
        forget = parser.parse_args(
            ["forget", "--session", "session-1", "--provider", "grok"]
        )

        self.assertEqual(init.clients, ["grok"])
        self.assertEqual(hook.provider, "grok")
        self.assertEqual(forget.provider, "grok")


if __name__ == "__main__":
    unittest.main()
