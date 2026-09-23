from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skill_picker.catalog import load_actions, load_skills


class LoadSkillsTests(unittest.TestCase):
    def test_loads_multiline_description_and_skips_hidden_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skills_dir = Path(directory)
            visible = skills_dir / "visible"
            visible.mkdir()
            (visible / "SKILL.md").write_text(
                """---
name: visible
description: >
  Handles complicated
  visible work.
user-invocable: true
disable-model-invocation: true
---

# Visible

Follow the visible workflow.
""",
                encoding="utf-8",
            )
            hidden = skills_dir / "hidden"
            hidden.mkdir()
            (hidden / "SKILL.md").write_text(
                """---
name: hidden
description: Internal only.
user-invocable: false
---
""",
                encoding="utf-8",
            )

            skills = load_skills(skills_dir)

        self.assertEqual([skill.name for skill in skills], ["visible"])
        self.assertEqual(skills[0].description, "Handles complicated visible work.")
        self.assertIn("Follow the visible workflow.", skills[0].opening)

    def test_loads_deterministic_script_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "actions.json"
            path.write_text(
                """[
  {
    "name": "session-viewer",
    "description": "Render a session as searchable HTML.",
    "command": "session-viewer"
  }
]""",
                encoding="utf-8",
            )

            actions = load_actions(path)

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].name, "session-viewer")
        self.assertEqual(actions[0].kind, "script")
        self.assertEqual(actions[0].invocation, "session-viewer")


if __name__ == "__main__":
    unittest.main()
