from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wikibrain.wikimap_adapter import WikimapAdapter, WikimapError


class WikimapAdapterTests(unittest.TestCase):
    def test_search_passes_requested_candidate_limit(self) -> None:
        adapter = WikimapAdapter(Path.cwd(), "/bin/echo")
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"results": []}',
            stderr="",
        )
        with patch(
            "wikibrain.wikimap_adapter.subprocess.run",
            return_value=completed,
        ) as run:
            adapter.search("project marker", 37)
        command = run.call_args.args[0]
        self.assertEqual(
            command,
            ["/bin/echo", "search", "project marker", "-n", "37", "--json"],
        )

    def test_non_executable_or_broken_command_is_not_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wikimap"
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o600)
            adapter = WikimapAdapter(Path(temporary), str(path))
            self.assertFalse(adapter.available)
            self.assertIsNone(adapter.version())

        false_command = "/usr/bin/false" if Path("/usr/bin/false").exists() else "/bin/false"
        self.assertTrue(os.access(false_command, os.X_OK))
        adapter = WikimapAdapter(Path.cwd(), false_command)
        self.assertTrue(adapter.available)
        self.assertIsNone(adapter.version())

    def test_doctor_rejects_structured_unhealthy_result(self) -> None:
        adapter = WikimapAdapter(Path.cwd(), "/bin/echo")
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"healthy": false, "index": {"pending": 3}}',
            stderr="",
        )
        with patch(
            "wikibrain.wikimap_adapter.subprocess.run",
            return_value=completed,
        ):
            with self.assertRaises(WikimapError):
                adapter.doctor()


if __name__ == "__main__":
    unittest.main()
