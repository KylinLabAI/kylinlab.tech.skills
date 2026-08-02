#!/usr/bin/env python3
"""Manage local skills by creating symlinks across agent skill directories.

skill-manager is responsible ONLY for symlinking local skill directories into
the agent runtimes. It does not clone or install external skills — external
skills are installed separately with ``npx skills add`` (see
``external-skills/README.md``).

Because links point at the skill source, edits to a linked local skill are
reflected in every agent runtime immediately.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Fix Unicode output on Windows.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AGENT_DIRS: tuple[str, ...] = (
    os.path.expanduser("~/.trae-cn/skills"),
    os.path.expanduser("~/.claude/skills"),
    os.path.expanduser("~/.codebuddy/skills"),
    os.path.expanduser("~/.qoder/skills"),
    os.path.expanduser("~/.qoder-cn/skills"),
    os.path.expanduser("~/.lingma/skills"),
    os.path.expanduser("~/.zcode/skills"),
    os.path.expanduser("~/.agents/skills"),
)

# Only allow safe skill names: alphanumerics, dashes, dots, and underscores.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _valid_skill_name(name: str) -> bool:
    """Return True if *name* is a safe skill identifier (no path separators)."""
    return bool(_SAFE_NAME.fullmatch(name))


def create_symlink(source: str, target: str) -> bool:
    """Create a symlink at *target* pointing to *source*.

    If *target* already exists as a symlink it is replaced. If *target* exists
    as a real file or directory, it is left untouched and an error is raised —
    skill-manager never deletes user data.
    """
    if os.path.islink(target):
        os.remove(target)
    elif os.path.exists(target):
        raise OSError(f"{target} exists and is not a symlink; refusing to replace it")
    os.symlink(source, target)
    return True


def remove_symlink(target: str) -> bool:
    """Remove the symlink at *target* if it is one; return True if removed."""
    if os.path.islink(target):
        os.remove(target)
        return True
    return False


def add_skill(source: str) -> int:
    """Symlink the local skill directory at *source* into every agent dir."""
    source = os.path.abspath(source)
    if not os.path.isdir(source):
        print(f"Error: source is not a directory: {source}", file=sys.stderr)
        return 1

    skill_name = os.path.basename(source)
    if not _valid_skill_name(skill_name):
        print(
            f"Error: invalid skill name {skill_name!r}; use only letters, "
            "digits, '-', '_', '.'",
            file=sys.stderr,
        )
        return 1

    skill_md = os.path.join(source, "SKILL.md")
    if not os.path.isfile(skill_md):
        print(f"Warning: SKILL.md not found in {source}", file=sys.stderr)

    print(f"\nCreating symlinks for skill: {skill_name}")
    print(f"Source: {source}")

    created = 0
    for agent_dir in AGENT_DIRS:
        os.makedirs(agent_dir, exist_ok=True)
        symlink_path = os.path.join(agent_dir, skill_name)
        try:
            create_symlink(source, symlink_path)
            print(f"  ✓ {agent_dir}")
            created += 1
        except OSError as exc:
            print(f"  ✗ {agent_dir}: {exc}")

    print(f"\nCreated {created} symlinks.")
    return 0


def remove_skill(skill_name: str) -> int:
    """Remove the symlink named *skill_name* from every agent dir."""
    if not _valid_skill_name(skill_name):
        print(
            f"Error: invalid skill name {skill_name!r}; use only letters, "
            "digits, '-', '_', '.'",
            file=sys.stderr,
        )
        return 1

    print(f"\nRemoving symlinks for skill: {skill_name}")

    removed = 0
    for agent_dir in AGENT_DIRS:
        symlink_path = os.path.join(agent_dir, skill_name)
        try:
            if remove_symlink(symlink_path):
                print(f"  ✓ {agent_dir}")
                removed += 1
            else:
                print(f"  - {agent_dir} (not a symlink or doesn't exist)")
        except OSError as exc:
            print(f"  ✗ {agent_dir}: {exc}")

    print(f"\nRemoved {removed} symlinks.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="manage.py",
        description="Symlink local skills into agent skill directories.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Symlink a local skill directory into agents")
    add.add_argument("source", help="Absolute path to the local skill directory")
    add.set_defaults(func=add_skill)

    rm = sub.add_parser("remove", help="Remove a skill's symlinks from agents")
    rm.add_argument("skill_name", help="Skill name (matches the symlink name)")
    rm.set_defaults(func=remove_skill)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "add":
        return args.func(args.source)
    if args.command == "remove":
        return args.func(args.skill_name)
    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
