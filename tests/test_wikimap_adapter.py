from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wikibrain.wikimap_adapter import WikimapAdapter, WikimapError


class WikimapAdapterTests(unittest.TestCase):
    def test_search_passes_requested_candidate_limit(self) -> None:
        adapter = WikimapAdapter(Path.cwd(), sys.executable)
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
            [sys.executable, "search", "project marker", "-n", "37", "--json"],
        )

    def test_non_executable_or_broken_command_is_not_healthy(self) -> None:
        if os.name != "nt":
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "wikimap"
                path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                path.chmod(0o600)
                adapter = WikimapAdapter(Path(temporary), str(path))
                self.assertFalse(adapter.available)
                self.assertIsNone(adapter.version())

        missing = Path(tempfile.gettempdir()) / "missing-wikimap-command"
        adapter = WikimapAdapter(Path.cwd(), str(missing))
        self.assertFalse(adapter.available)
        self.assertIsNone(adapter.version())

        adapter = WikimapAdapter(Path.cwd(), sys.executable)
        failed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="broken",
        )
        with patch(
            "wikibrain.wikimap_adapter.subprocess.run",
            return_value=failed,
        ):
            self.assertTrue(adapter.available)
            self.assertIsNone(adapter.version())

    def test_doctor_rejects_structured_unhealthy_result(self) -> None:
        adapter = WikimapAdapter(Path.cwd(), sys.executable)
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

    def test_python_script_command_uses_current_interpreter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "fake_wikimap.py"
            script.write_text("print('unused')\n", encoding="utf-8")
            adapter = WikimapAdapter(Path(temporary), str(script))
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="wikimap 1.1.0-fake\n",
                stderr="",
            )
            with patch(
                "wikibrain.wikimap_adapter.subprocess.run",
                return_value=completed,
            ) as run:
                self.assertEqual(adapter.version(), "wikimap 1.1.0-fake")
            self.assertEqual(
                run.call_args.args[0],
                [sys.executable, str(script), "--version"],
            )


if __name__ == "__main__":
    unittest.main()
