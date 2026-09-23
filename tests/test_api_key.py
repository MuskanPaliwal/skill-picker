from __future__ import annotations

import contextlib
import io
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from skill_picker import typesafe
from skill_picker.typesafe import RouterUnavailable, default_key_file, resolve_api_key

SECRET = "sk-live-do-not-print-me"

PRINT_KEY = f"{sys.executable} -c \"print('from-command')\""


class ResolveApiKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config_home = Path(
            self.enterContext(tempfile.TemporaryDirectory())
        )
        self.env = {"XDG_CONFIG_HOME": str(self.config_home)}

    def write_key_file(self, contents: str, mode: int = 0o600) -> Path:
        path = default_key_file(self.env)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        path.chmod(mode)
        return path

    def test_environment_variable_wins(self) -> None:
        self.write_key_file("from-file\n")
        env = {
            **self.env,
            "TYPESAFE_API_KEY": "  from-env  ",
            "TYPESAFE_API_KEY_COMMAND": PRINT_KEY,
        }

        self.assertEqual(resolve_api_key(env), "from-env")

    def test_blank_environment_variable_falls_through(self) -> None:
        self.write_key_file("from-file\n")
        env = {**self.env, "TYPESAFE_API_KEY": "   "}

        self.assertEqual(resolve_api_key(env), "from-file")

    def test_helper_command_runs_without_a_shell(self) -> None:
        self.write_key_file("from-file\n")
        env = {**self.env, "TYPESAFE_API_KEY_COMMAND": PRINT_KEY}

        self.assertEqual(resolve_api_key(env), "from-command")

    def test_helper_command_shell_metacharacters_are_not_expanded(self) -> None:
        env = {
            **self.env,
            "TYPESAFE_API_KEY_COMMAND": (
                f'{sys.executable} -c "import sys; print(sys.argv[1])" $(whoami)'
            ),
        }

        self.assertEqual(resolve_api_key(env), "$(whoami)")

    def test_failing_helper_command_is_reported(self) -> None:
        env = {
            **self.env,
            "TYPESAFE_API_KEY_COMMAND": (
                f'{sys.executable} -c "raise SystemExit(3)"'
            ),
        }

        with self.assertRaises(RouterUnavailable) as raised:
            resolve_api_key(env)

        self.assertIn("TYPESAFE_API_KEY_COMMAND", str(raised.exception))

    def test_silent_helper_command_is_reported(self) -> None:
        env = {
            **self.env,
            "TYPESAFE_API_KEY_COMMAND": f"{sys.executable} -c pass",
        }

        with self.assertRaises(RouterUnavailable):
            resolve_api_key(env)

    def test_missing_helper_executable_is_reported(self) -> None:
        env = {**self.env, "TYPESAFE_API_KEY_COMMAND": "definitely-not-installed"}

        with self.assertRaises(RouterUnavailable):
            resolve_api_key(env)

    def test_key_file_is_read_and_trimmed(self) -> None:
        self.write_key_file("from-file\n")

        self.assertEqual(resolve_api_key(self.env), "from-file")

    def test_readable_by_others_key_file_warns_but_works(self) -> None:
        path = self.write_key_file("from-file\n", mode=0o644)

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            key = resolve_api_key(self.env)

        self.assertEqual(key, "from-file")
        self.assertIn(str(path), stderr.getvalue())
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o644)

    def test_no_source_returns_none(self) -> None:
        self.assertIsNone(resolve_api_key(self.env))

    def test_helper_stderr_never_reaches_the_error_message(self) -> None:
        env = {
            **self.env,
            "TYPESAFE_API_KEY_COMMAND": (
                f'{sys.executable} -c "import sys; '
                f"sys.stderr.write('{SECRET}'); raise SystemExit(1)\""
            ),
        }

        with self.assertRaises(RouterUnavailable) as raised:
            resolve_api_key(env)

        self.assertNotIn(SECRET, str(raised.exception))

    def test_timed_out_helper_never_reports_its_arguments(self) -> None:
        env = {
            **self.env,
            "TYPESAFE_API_KEY_COMMAND": (
                f'{sys.executable} -c "import time; '
                f"print('{SECRET}'); time.sleep(5)\""
            ),
        }

        with mock.patch.object(typesafe, "KEY_COMMAND_TIMEOUT", 0.3):
            with self.assertRaises(RouterUnavailable) as raised:
                resolve_api_key(env)

        self.assertNotIn(SECRET, str(raised.exception))

    def test_key_file_follows_injected_home(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / ".config" / "typesafe" / "api-key"
            path.parent.mkdir(parents=True)
            path.write_text("from-home\n", encoding="utf-8")
            path.chmod(0o600)

            self.assertEqual(resolve_api_key({"HOME": home}), "from-home")


if __name__ == "__main__":
    unittest.main()
