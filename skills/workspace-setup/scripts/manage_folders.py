#!/usr/bin/env python3
"""Scan and rebuild a workspace folder tree with repo-aware filtering.

Commands:
  scan    - Walk a workspace, record git repos + their ancestor folders +
            symlinks to repos. Pure folders (no repos inside) are excluded.
  rebuild - Recreate the folder structure, clone repos, and restore symlinks
            from a config file.

This is a generic, user-driven skill: it works on any workspace root and never
hardcodes repo names or paths. Output configs are portable JSON files.

Design notes (see SKILL.md):
  * Repo remotes and branches are captured so a tree can be recreated elsewhere.
  * Folder structure is preserved exactly (e.g. app/tool/repo-4).
  * Symlink targets are stored relative to the workspace root for portability.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# shared constants / helpers
# ---------------------------------------------------------------------------

SKIP_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "node_modules", "build", "dist", "target", ".venv", "venv",
}

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIGS_DIR = SCRIPT_DIR.parent / "configs"


def resolve(path: Path) -> Path:
    return path.expanduser().resolve()


def user_relative(path: Path) -> str:
    resolved = resolve(path)
    home = Path.home().resolve()
    try:
        rel = resolved.relative_to(home)
    except ValueError:
        return str(resolved)
    return "~" if not rel.parts else f"~/{rel.as_posix()}"


def workspace_relative(path: Path, workspace: Path) -> str:
    """Return *path* relative to *workspace* without following symlinks."""
    workspace_str = str(workspace.resolve())
    path_str = os.path.abspath(str(path))
    try:
        rel = os.path.relpath(path_str, workspace_str)
        return Path(rel).as_posix() or "."
    except ValueError:
        return path_str


def same_file_path(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except OSError:
        return left.resolve() == right.resolve()


def is_git_repo(path: Path) -> bool:
    """True if *path* is the root of a git repository."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False
        return same_file_path(Path(result.stdout.strip()), path)
    except Exception:
        return False


def repo_remote(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(path), "config", "--get", "remote.origin.url"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def repo_branch(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(path), "branch", "--show-current"],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return f"detached@{result.stdout.strip()}"
    return None


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

def _scan_repo_symlinks(workspace: Path, repo_path: Path, entries: list[dict[str, Any]]) -> None:
    """Scan a repo's immediate children for symlinks that point to other repos.

    This captures repo-root symlinks (e.g. config repo) that link to other
    repos within the workspace. Only direct children are checked — deeper
    recursion into a repo is intentionally avoided.
    """
    try:
        children = sorted(
            [repo_path / name for name in os.listdir(repo_path)],
            key=lambda p: p.name,
        )
    except OSError:
        return

    for child in children:
        if child.name in SKIP_DIRS:
            continue
        if child.is_symlink():
            try:
                target = child.resolve()
            except OSError:
                continue
            if target.is_dir() and is_git_repo(target):
                entries.append({
                    "path": workspace_relative(child, workspace),
                    "type": "symlink",
                    "target": workspace_relative(target, workspace),
                })


def scan_dir(workspace: Path, current: Path, entries: list[dict[str, Any]]) -> bool:
    """Recursively scan *current*. Returns True if this subtree contains
    anything worth recording (repo, symlink-to-repo, or ancestor folder)."""

    # --- symlink handling --------------------------------------------------
    if current.is_symlink():
        try:
            target = current.resolve()
        except OSError:
            return False
        if not target.is_dir():
            return False
        if is_git_repo(target):
            entries.append({
                "path": workspace_relative(current, workspace),
                "type": "symlink",
                "target": workspace_relative(target, workspace),
            })
            return True
        return False

    # --- repo detection ----------------------------------------------------
    if current.is_dir() and is_git_repo(current):
        entries.append({
            "path": workspace_relative(current, workspace),
            "type": "repo",
            "remote": repo_remote(current),
            "branch": repo_branch(current),
        })
        _scan_repo_symlinks(workspace, current, entries)
        return True

    # --- ordinary directory - recurse --------------------------------------
    if not current.is_dir():
        return False

    child_has_content = False
    try:
        children = sorted(
            [current / name for name in os.listdir(current)],
            key=lambda p: p.name,
        )
    except OSError:
        return False

    for child in children:
        if child.name in SKIP_DIRS:
            continue
        if scan_dir(workspace, child, entries):
            child_has_content = True

    if child_has_content and current != workspace:
        entries.append({
            "path": workspace_relative(current, workspace),
            "type": "folder",
        })
    return child_has_content


def command_scan(args: argparse.Namespace) -> int:
    workspace = resolve(args.workspace)
    if not workspace.is_dir():
        print(f"ERROR: workspace does not exist: {workspace}", file=sys.stderr)
        return 1

    entries: list[dict[str, Any]] = []
    scan_dir(workspace, workspace, entries)

    def _sort_key(item: dict[str, Any]) -> tuple[int, str, int]:
        type_order = {"folder": 0, "repo": 1, "symlink": 2}
        return (
            len(Path(str(item["path"])).parts),
            str(item["path"]),
            type_order.get(str(item.get("type")), 9),
        )

    entries.sort(key=_sort_key)

    manifest = {
        "schema_version": 1,
        "workspace": user_relative(workspace),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "folders": sum(1 for e in entries if e["type"] == "folder"),
        "repos": sum(1 for e in entries if e["type"] == "repo"),
        "symlinks": sum(1 for e in entries if e["type"] == "symlink"),
        "entries": entries,
    }

    output = resolve(args.output)
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        print(f"\nWould write to: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"Workspace : {workspace}")
    print(f"Folders   : {manifest['folders']}")
    print(f"Repos     : {manifest['repos']}")
    print(f"Symlinks  : {manifest['symlinks']}")
    print(f"Written   : {output}")

    missing = [e["path"] for e in entries if e.get("type") == "repo" and not e.get("remote")]
    if missing:
        print("\nWARNING: these repos have no origin remote and cannot be cloned:")
        for path in missing:
            print(f"  - {path}")
    return 0


# ---------------------------------------------------------------------------
# rebuild
# ---------------------------------------------------------------------------

def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Config file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Config file is not valid JSON: {path}\n{exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise SystemExit(f"Config file has unexpected structure: {path}")
    return data


def path_has_content(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        return any(path.iterdir())
    return True


def command_rebuild(args: argparse.Namespace) -> int:
    manifest = load_manifest(resolve(args.config))
    target = resolve(args.target)

    entries = [e for e in manifest["entries"] if isinstance(e, dict)]

    # ---- Phase 1: create folders ------------------------------------------
    folder_entries = [e for e in entries if e["type"] == "folder"]
    folder_entries.sort(key=lambda e: len(Path(str(e["path"])).parts))

    print("=== Creating folders ===")
    for entry in folder_entries:
        path = target / str(entry["path"])
        if args.dry_run:
            print(f"  [dry-run] mkdir: {path}")
        else:
            path.mkdir(parents=True, exist_ok=True)
            print(f"  created: {path}")

    # ---- Phase 2: clone / update repos ------------------------------------
    repo_entries = [e for e in entries if e["type"] == "repo"]

    print("\n=== Repositories ===")
    for entry in repo_entries:
        rel_path = str(entry["path"])
        dest = target / rel_path
        remote = entry.get("remote")
        branch = entry.get("branch")

        if dest.is_dir() and is_git_repo(dest):
            if args.update_existing:
                if args.dry_run:
                    print(f"  [dry-run] pull --ff-only: {rel_path}")
                    continue
                result = subprocess.run(
                    ["git", "-C", str(dest), "pull", "--ff-only"],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    print(f"  FAILED to update: {rel_path} - {result.stderr.strip()}")
                else:
                    print(f"  updated: {rel_path}")
            else:
                print(f"  skipped (existing repo): {rel_path}")
            continue

        if path_has_content(dest):
            print(f"  BLOCKED: {rel_path} - path exists and is not empty")
            continue

        if not remote:
            print(f"  SKIPPED: {rel_path} - no origin remote in manifest")
            continue

        if args.dry_run:
            print(f"  [dry-run] clone {remote} -> {rel_path}")
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", str(remote), str(dest)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  FAILED clone: {rel_path} - {result.stderr.strip()}")
            continue

        if branch and not str(branch).startswith("detached@"):
            checkout = subprocess.run(
                ["git", "-C", str(dest), "checkout", str(branch)],
                capture_output=True, text=True,
            )
            if checkout.returncode != 0:
                print(f"  cloned but checkout failed: {rel_path} -> {branch}")
            else:
                print(f"  cloned + checked out {branch}: {rel_path}")
        else:
            print(f"  cloned: {rel_path}")

    # ---- Phase 3: symlinks ------------------------------------------------
    symlink_entries = [e for e in entries if e["type"] == "symlink"]

    if symlink_entries:
        print("\n=== Symlinks ===")
        for entry in symlink_entries:
            rel_path = str(entry["path"])
            link_path = target / rel_path
            target_rel = entry.get("target")
            if not target_rel:
                print(f"  SKIPPED: {rel_path} - no target in manifest")
                continue

            if link_path.is_symlink() or link_path.exists():
                print(f"  skipped (exists): {rel_path}")
                continue

            absolute_target = target_rel if os.path.isabs(target_rel) \
                else os.path.normpath(str(target / target_rel))

            try:
                symlink_value = os.path.relpath(absolute_target, str(link_path.parent))
            except ValueError:
                symlink_value = absolute_target

            if args.dry_run:
                print(f"  [dry-run] symlink: {rel_path} -> {symlink_value}")
                continue

            link_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                link_path.symlink_to(symlink_value)
                print(f"  linked: {rel_path} -> {symlink_value}")
            except OSError as exc:
                print(f"  FAILED: {rel_path} - {exc}")

    if args.dry_run:
        print("\n[dry-run] No changes were made.")
    else:
        print("\nDone.")

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Scan and rebuild a workspace folder tree (repo-aware filtering)."
    )
    sub = root.add_subparsers(dest="command", required=True)

    # scan ----------------------------------------------------------------
    scan = sub.add_parser("scan", help="Scan a folder tree and save its structure.")
    scan.add_argument("--workspace", type=Path, required=True,
                      help="Path to the workspace root folder.")
    scan.add_argument("--output", type=Path, default=None,
                      help="Path to write the config JSON file. "
                           f"Default: {DEFAULT_CONFIGS_DIR}/<workspace-name>.json")
    scan.add_argument("--dry-run", action="store_true",
                      help="Print the JSON to stdout instead of writing.")

    # rebuild -------------------------------------------------------------
    rebuild = sub.add_parser("rebuild", help="Rebuild the folder tree from a config file.")
    rebuild.add_argument("--config", type=Path, required=True,
                         help="Path to the config JSON file (from scan).")
    rebuild.add_argument("--target", type=Path, required=True,
                         help="Target directory to rebuild the tree into.")
    rebuild.add_argument("--update-existing", action="store_true",
                         help="Run 'git pull --ff-only' for existing repos.")
    rebuild.add_argument("--dry-run", action="store_true",
                         help="Preview actions without making changes.")

    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "scan":
        if args.output is None:
            name = resolve(args.workspace).name or "workspace"
            args.output = DEFAULT_CONFIGS_DIR / f"{name}.json"
        return command_scan(args)
    if args.command == "rebuild":
        return command_rebuild(args)
    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
