from __future__ import annotations

import json
import unittest

from wikibrain.redaction import REDACTED, redact_text, sanitize_value


class RedactionTests(unittest.TestCase):
    def test_common_secret_shapes_are_removed(self) -> None:
        secrets = [
            "sk-ant-api03-abcdefghijklmnopqrstuv",
            "sk-proj-abcdefghijklmnopqrstuv",
            "ghp_abcdefghijklmnopqrstuvwxyz123456",
            "AKIAABCDEFGHIJKLMNOP",
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
            "password=hunter2-secret",
            "postgres://user:supersecret@example.test/db",
            "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
        ]
        original = "\n".join(secrets)
        result = redact_text(original)
        self.assertGreaterEqual(result.count, len(secrets))
        self.assertIn(REDACTED, result.text)
        for forbidden in (
            "hunter2-secret",
            "supersecret",
            "abcdefghijklmnopqrstuv",
            "\nsecret\n",
        ):
            self.assertNotIn(forbidden, result.text)

    def test_sanitizer_omits_raw_tool_outputs(self) -> None:
        payload = {
            "file_path": "src/app.py",
            "tool_response": "should disappear",
            "nested": {"content": "also disappears", "query": "safe"},
        }
        cleaned = sanitize_value(payload)
        self.assertNotIn("tool_response", cleaned)
        self.assertNotIn("content", cleaned["nested"])
        self.assertEqual(cleaned["nested"]["query"], "safe")

    def test_sensitive_environment_assignments_keep_names_not_values(self) -> None:
        assignments = {
            "DISCORD_BOT_TOKEN": "discord-value-that-must-not-survive",
            "AWS_SECRET_ACCESS_KEY": "aws-value-that-must-not-survive",
            "export OPENAI_API_KEY": "openai-value-that-must-not-survive",
        }
        original = "\n".join(
            (
                f'{name}="{value}"'
                if name.startswith("export ")
                else f"{name}={value}"
            )
            for name, value in assignments.items()
        )
        original += (
            "\nAWS_REGION=ap-northeast-2"
            "\nTOKENIZER_MODEL=sentencepiece"
            "\nTOKENIZER: model-name"
        )

        result = redact_text(original)

        for name, value in assignments.items():
            self.assertIn(name, result.text)
            self.assertNotIn(value, result.text)
        self.assertIn(f'export OPENAI_API_KEY="{REDACTED}"', result.text)
        self.assertIn(f"DISCORD_BOT_TOKEN={REDACTED}", result.text)
        self.assertIn(f"AWS_SECRET_ACCESS_KEY={REDACTED}", result.text)
        self.assertIn("AWS_REGION=ap-northeast-2", result.text)
        self.assertIn("TOKENIZER_MODEL=sentencepiece", result.text)
        self.assertIn("TOKENIZER: model-name", result.text)

    def test_structured_service_tokens_are_removed(self) -> None:
        tokens = {
            "slack": (
                "xoxb-123456789012-123456789012-"
                "abcdefghijklmnopqrstuvwxyzABCDEF"
            ),
            "jwt": (
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
                "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
            ),
            "discord": (
                "MTIzNDU2Nzg5MDEyMzQ1Njc4.AbCdEf."
                "abcdefghijklmnopqrstuvwxyzABCDE"
            ),
            "gitlab": "glpat-abcdefghijklmnopqrstuvwxyz123456",
            "npm": "npm_abcdefghijklmnopqrstuvwxyz1234567890",
            "github-fine-grained": (
                "github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "0123456789abcdefghijklmnopqrstuv"
            ),
            "huggingface": "hf_abcdefghijklmnopqrstuvwxyz1234567890",
            "google": "AIza" + ("A" * 35),
            "stripe-secret": "_".join(
                ("sk", "live", "abcdefghijklmnopqrstuvwxyz123456")
            ),
            "stripe-restricted": "_".join(
                ("rk", "live", "abcdefghijklmnopqrstuvwxyz123456")
            ),
            "pypi": "pypi-AgEIcHlwaS5vcmcCJDabcdefghijklmnopqrstuvwxyz",
        }
        result = redact_text("\n".join(tokens.values()))

        for kind, token in tokens.items():
            with self.subTest(kind=kind):
                self.assertNotIn(token, result.text)
                self.assertEqual(redact_text(token).text, REDACTED)
        self.assertEqual(result.text.count(REDACTED), len(tokens))
        self.assertTrue(
            {
                "slack-token",
                "jwt",
                "discord-token",
                "gitlab-token",
                "npm-token",
                "github-fine-grained-token",
                "huggingface-token",
                "google-api-key",
                "stripe-live-key",
                "pypi-token",
            }.issubset(result.kinds)
        )

    def test_json_and_yaml_sensitive_values_remain_readable(self) -> None:
        examples = {
            '{"DISCORD_BOT_TOKEN":"json-secret","safe":"visible"}': (
                '{"DISCORD_BOT_TOKEN":"[REDACTED]","safe":"visible"}'
            ),
            '{"DISCORD_BOT_TOKEN":"abc\\"def","safe":"visible"}': (
                '{"DISCORD_BOT_TOKEN":"[REDACTED]","safe":"visible"}'
            ),
            '{"DISCORD_BOT_TOKEN":12345,"safe":"visible"}': (
                '{"DISCORD_BOT_TOKEN":"[REDACTED]","safe":"visible"}'
            ),
            '"AWS_SECRET_ACCESS_KEY": "aws-secret"': (
                '"AWS_SECRET_ACCESS_KEY": "[REDACTED]"'
            ),
            "DISCORD_BOT_TOKEN: yaml-secret\nsafe: visible": (
                "DISCORD_BOT_TOKEN: [REDACTED]\nsafe: visible"
            ),
            "AWS_SECRET_ACCESS_KEY: 'aws-secret'": (
                "AWS_SECRET_ACCESS_KEY: '[REDACTED]'"
            ),
            '{"api-key":"dash-secret","safe":"visible"}': (
                '{"api-key":"[REDACTED]","safe":"visible"}'
            ),
            '{"clientSecret":"client-secret","safe":"visible"}': (
                '{"clientSecret":"[REDACTED]","safe":"visible"}'
            ),
            "apiKey: camel-secret\nsafe: visible": (
                "apiKey: [REDACTED]\nsafe: visible"
            ),
            "_authToken: auth-secret": "_authToken: [REDACTED]",
        }

        for original, expected in examples.items():
            with self.subTest(original=original):
                redacted = redact_text(original).text
                self.assertEqual(redacted, expected)
                if redacted.startswith("{"):
                    self.assertEqual(json.loads(redacted)["safe"], "visible")

    def test_sanitized_payload_is_serializable_without_new_secret_shapes(self) -> None:
        secrets = (
            "_".join(("sk", "live", "abcdefghijklmnopqrstuvwxyz123456")),
            "_".join(("rk", "live", "abcdefghijklmnopqrstuvwxyz123456")),
            "pypi-AgEIcHlwaS5vcmcCJDabcdefghijklmnopqrstuvwxyz",
            "client-secret-that-must-not-persist",
        )
        payload = {
            "prompt": f'{{"clientSecret":"{secrets[3]}"}}',
            "note": " ".join(secrets[:3]),
            "tokenizer": "TOKENIZER: sentencepiece",
        }

        cleaned = sanitize_value(payload)
        persisted = json.dumps(cleaned, sort_keys=True)

        self.assertEqual(json.loads(persisted), cleaned)
        self.assertIn(REDACTED, persisted)
        self.assertIn("TOKENIZER: sentencepiece", persisted)
        for secret in secrets:
            self.assertNotIn(secret, persisted)

    def test_encrypted_private_key_block_is_removed_as_a_whole(self) -> None:
        private_key = (
            "-----BEGIN ENCRYPTED PRIVATE KEY-----\n"
            "cHJpdmF0ZS1rZXktbWF0ZXJpYWw=\n"
            "-----END ENCRYPTED PRIVATE KEY-----"
        )
        self.assertEqual(redact_text(private_key).text, REDACTED)


if __name__ == "__main__":
    unittest.main()
