#!/usr/bin/env python3
"""Install tools required by the disk-cleanup skill via the laptop-setup skill.

Usage:
    python <skill>/scripts/init.py [--list|--check|--install] [profile ...] [extra args]
"""

import os
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
APPS_FILE = SKILL_DIR / "configs" / "apps.yaml"
DEFAULT_PROFILE = "disk-cleanup"


def find_laptop_setup() -> Path:
    env = os.environ.get("LAPTOP_SETUP")
    if env:
        p = Path(env)
        if (p / "scripts" / "laptop_setup.py").is_file():
            return p
    sibling = SKILL_DIR.parent / "laptop-setup"
    if (sibling / "scripts" / "laptop_setup.py").is_file():
        return sibling
    print("ERROR: laptop-setup not found. Set LAPTOP_SETUP=/path/to/laptop-setup",
          file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if not APPS_FILE.is_file():
        print(f"ERROR: apps.yaml not found at {APPS_FILE}", file=sys.stderr)
        sys.exit(1)

    laptop_setup = find_laptop_setup()
    setup_script = laptop_setup / "scripts" / "laptop_setup.py"

    action = "--install"
    profiles: list[str] = []
    extra_args: list[str] = []

    for arg in sys.argv[1:]:
        if arg in ("--list", "--check", "--install"):
            action = arg
        elif arg.startswith("--"):
            extra_args.append(arg)
        else:
            profiles.append(arg)

    if not profiles:
        profiles = [DEFAULT_PROFILE]

    profile_args: list[str] = []
    for p in profiles:
        profile_args.extend(["--profile", p])

    cmd = [
        sys.executable, str(setup_script), action,
        "--apps-file", str(APPS_FILE),
        *profile_args, *extra_args,
    ]
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
