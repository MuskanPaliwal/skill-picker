"""Suggest which of a user's skills fit a request. Prints JSON; takes no action."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .catalog import (
    default_actions_path,
    default_skills_dir,
    load_catalog,
)
from .router import (
    DEFAULT_FIT_FLOOR,
    DEFAULT_GATE_FLOOR,
    DEFAULT_SHORTLIST_SIZE,
    has_explicit_command_invocation,
    has_explicit_invocation,
    recommend,
)
from .typesafe import (
    DEFAULT_MODEL,
    KEY_COMMAND_ENV,
    KEY_ENV,
    RouterUnavailable,
    call_typesafe,
    default_key_file,
    resolve_api_key,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--request",
        help="request text; agents should prefer stdin to avoid shell interpolation",
    )
    parser.add_argument("--skills-dir", type=Path)
    parser.add_argument(
        "--actions",
        type=Path,
        help="JSON array of deterministic commands to rank alongside skills",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--gate-floor", type=float, default=DEFAULT_GATE_FLOOR)
    parser.add_argument("--fit-floor", type=float, default=DEFAULT_FIT_FLOOR)
    parser.add_argument(
        "--shortlist-size", type=int, default=DEFAULT_SHORTLIST_SIZE
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def _read_request(args: argparse.Namespace) -> str:
    if args.request is not None:
        return args.request.strip()
    return sys.stdin.read().strip()


def _no_key_reason() -> str:
    return (
        f"no API key: set {KEY_ENV}, set {KEY_COMMAND_ENV} to a command that "
        f"prints it, or write it to {default_key_file()}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    request = _read_request(args)
    if not request:
        parser.error("provide the current user request on stdin or with --request")

    skills_dir = args.skills_dir.expanduser() if args.skills_dir else default_skills_dir()
    actions_path = args.actions.expanduser() if args.actions else default_actions_path()

    try:
        skills = load_catalog(skills_dir, actions_path)
        explicit = has_explicit_invocation(
            request,
            {skill.name for skill in skills if skill.kind == "skill"},
        ) or has_explicit_command_invocation(
            request,
            {
                skill.invocation or skill.name
                for skill in skills
                if skill.kind == "script"
            },
        )
        if explicit:
            result = {
                "status": "skipped",
                "reason": "explicit_action_invocation",
                "suggestions": [],
            }
        elif api_key := resolve_api_key():
            result = recommend(
                request,
                skills,
                lambda payload: call_typesafe(
                    payload, api_key=api_key, timeout=args.timeout
                ),
                model=args.model,
                gate_floor=args.gate_floor,
                fit_floor=args.fit_floor,
                shortlist_size=args.shortlist_size,
            )
        else:
            result = {
                "status": "unavailable",
                "reason": _no_key_reason(),
                "suggestions": [],
            }
    except (KeyError, OSError, TypeError, ValueError, RouterUnavailable) as error:
        result = {
            "status": "unavailable",
            "reason": str(error),
            "suggestions": [],
        }

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
