from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from wikibrain.skill_installer import (
    install_skills,
    skill_status,
    uninstall_skills,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "plugins" / "wikibrain" / "skills" / "wikibrain"


class SkillInstallerTests(unittest.TestCase):
    def test_managed_skills_are_idempotent_and_removable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = {
                "claude": root / ".claude" / "skills" / "wikibrain",
                "agents": root / ".agents" / "skills" / "wikibrain",
            }
            first = install_skills(
                ["claude", "codex"], source=SOURCE, targets=targets
            )
            second = install_skills(
                ["claude", "codex"], source=SOURCE, targets=targets
            )
            self.assertEqual([item["changes"] for item in first], [1, 1])
            self.assertEqual([item["changes"] for item in second], [0, 0])
            self.assertTrue(all(item["managed"] for item in skill_status(
                ["claude", "codex"], targets=targets
            )))
            removed = uninstall_skills(
                ["claude", "codex"], targets=targets
            )
            self.assertEqual([item["changes"] for item in removed], [1, 1])
            self.assertTrue(all(not path.exists() for path in targets.values()))

    def test_custom_skill_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "custom" / "wikibrain"
            target.mkdir(parents=True)
            custom = target / "SKILL.md"
            custom.write_text(
                "---\nname: wikibrain\n"
                "description: My custom brain workflow.\n---\n",
                encoding="utf-8",
            )
            result = install_skills(
                ["claude"],
                source=SOURCE,
                targets={"claude": target},
            )
            self.assertEqual(result[0]["status"], "preserved-custom-skill")
            self.assertIn("custom brain", custom.read_text(encoding="utf-8"))
            removed = uninstall_skills(
                ["claude"], targets={"claude": target}
            )
            self.assertEqual(removed[0]["changes"], 0)
            self.assertTrue(target.exists())

    def test_failed_replacement_restores_managed_skill_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            target = root / ".agents" / "skills" / "wikibrain"
            shutil.copytree(SOURCE, source)
            install_skills(
                ["codex"], source=source, targets={"agents": target}
            )
            original = (target / "SKILL.md").read_text(encoding="utf-8")
            (source / "SKILL.md").write_text(
                original + "\n<!-- replacement -->\n", encoding="utf-8"
            )
            real_replace = os.replace
            calls = 0

            def fail_replacement(source_path: Any, target_path: Any) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated replacement failure")
                real_replace(source_path, target_path)

            with patch("wikibrain.skill_installer.os.replace", side_effect=fail_replacement):
                with self.assertRaisesRegex(OSError, "simulated replacement failure"):
                    install_skills(
                        ["codex"], source=source, targets={"agents": target}
                    )

            self.assertEqual(
                (target / "SKILL.md").read_text(encoding="utf-8"), original
            )
            self.assertEqual(list(target.parent.glob("wikibrain.*.bak")), [])

    def test_managed_symlink_backup_is_pruned_without_losing_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            linked = root / "linked-managed-skill"
            target = root / ".agents" / "skills" / "wikibrain"
            shutil.copytree(SOURCE, source)
            shutil.copytree(SOURCE, linked)
            target.parent.mkdir(parents=True)
            target.symlink_to(linked, target_is_directory=True)

            for index in range(4):
                skill = source / "SKILL.md"
                skill.write_text(
                    skill.read_text(encoding="utf-8")
                    + f"\n<!-- symlink revision {index} -->\n",
                    encoding="utf-8",
                )
                install_skills(
                    ["codex"],
                    source=source,
                    targets={"agents": target},
                )

            backups = sorted(target.parent.glob("wikibrain.*.bak"))
            self.assertEqual(len(backups), 3)
            self.assertTrue(target.is_dir())
            self.assertFalse(target.is_symlink())
            self.assertTrue(linked.is_dir())

    def test_managed_skill_keeps_only_the_three_newest_backups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            target = root / ".agents" / "skills" / "wikibrain"
            shutil.copytree(SOURCE, source)
            manual = target.parent / "wikibrain.manual.bak"
            manual.mkdir(parents=True)
            (manual / "note.txt").write_text("manual", encoding="utf-8")
            for index in range(6):
                skill = source / "SKILL.md"
                skill.write_text(
                    skill.read_text(encoding="utf-8")
                    + f"\n<!-- revision {index} -->\n",
                    encoding="utf-8",
                )
                install_skills(
                    ["codex"],
                    source=source,
                    targets={"agents": target},
                )

            backups = sorted(
                path
                for path in target.parent.glob("wikibrain.*.bak")
                if path != manual
            )
            self.assertEqual(len(backups), 3)
            self.assertTrue((manual / "note.txt").exists())


if __name__ == "__main__":
    unittest.main()
