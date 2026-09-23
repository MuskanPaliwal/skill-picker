"""TypeSafe API access and API key resolution."""

from __future__ import annotations

import json
import os
import shlex
import socket
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
KEY_ENV = "TYPESAFE_API_KEY"
KEY_COMMAND_ENV = "TYPESAFE_API_KEY_COMMAND"
KEY_FILE_RELATIVE = Path("typesafe") / "api-key"
# A helper command may prompt for biometric or password unlock before printing.
KEY_COMMAND_TIMEOUT = 30.0


class RouterUnavailable(RuntimeError):
    """The router could not produce a trustworthy recommendation."""


def default_key_file(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if configured := env.get("XDG_CONFIG_HOME"):
        base = Path(configured)
    elif home := env.get("HOME"):
        base = Path(home) / ".config"
    else:
        base = Path.home() / ".config"
    return base.expanduser() / KEY_FILE_RELATIVE


def _key_from_command(command: str) -> str:
    # Never report the child's output or arguments: either can carry the key.
    # stderr is inherited so an unlock prompt stays visible to the user.
    try:
        completed = subprocess.run(
            shlex.split(command),
            stdout=subprocess.PIPE,
            text=True,
            timeout=KEY_COMMAND_TIMEOUT,
        )
    except subprocess.TimeoutExpired as error:
        raise RouterUnavailable(
            f"{KEY_COMMAND_ENV} timed out after {KEY_COMMAND_TIMEOUT:g}s"
        ) from error
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise RouterUnavailable(f"{KEY_COMMAND_ENV} could not be run") from error
    if completed.returncode != 0:
        raise RouterUnavailable(
            f"{KEY_COMMAND_ENV} exited with status {completed.returncode}"
        )
    key = completed.stdout.strip()
    if not key:
        raise RouterUnavailable(f"{KEY_COMMAND_ENV} printed no key")
    return key


def _key_from_file(path: Path) -> str | None:
    try:
        info = path.stat()
        key = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not key:
        return None
    if stat.S_IMODE(info.st_mode) & 0o077:
        print(
            f"warning: {path} is readable by other users; run chmod 600 on it",
            file=sys.stderr,
        )
    return key


def resolve_api_key(env: Mapping[str, str] | None = None) -> str | None:
    """Return the API key from the environment, a helper command, or a key file.

    Returns None when no source is configured, which callers report as an
    unavailable router rather than an error.
    """
    env = os.environ if env is None else env

    if key := env.get(KEY_ENV, "").strip():
        return key
    if command := env.get(KEY_COMMAND_ENV, "").strip():
        return _key_from_command(command)
    return _key_from_file(default_key_file(env))


def call_typesafe(
    payload: dict[str, Any],
    *,
    api_key: str,
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "skill-picker/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RouterUnavailable(
            f"TypeSafe API returned HTTP {error.code}"
        ) from error
    except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
        raise RouterUnavailable("TypeSafe API could not be reached") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RouterUnavailable(
            "TypeSafe API returned an invalid response"
        ) from error
