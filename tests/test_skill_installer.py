from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
