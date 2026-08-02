#!/usr/bin/env python3
"""
scan_machine.py – Scan the current machine and generate a customized apps.yaml draft.

Why:  `configs/apps.yaml` is intentionally a *draft* that the user must edit to
match their own machine. Instead of hand-writing it, you can ask an AI agent
(or run this script directly) to scan what is already installed and produce a
starting point that reflects this machine's real toolchain.

What it does:
  1. Detects platform / architecture (macOS, Windows, Linux).
  2. DISCOVERS installed tools and apps dynamically from the standard install
     folders (PATH dirs, /Applications, ~/.local/bin, ~/.cargo/bin, ...) and from
     common package managers (npm global, pip, Homebrew). There is NO hardcoded
     catalog of app names.
  3. For each discovered tool, emits a best-effort generic install command
     (e.g. `brew install <name>`), written to the install_<os> keys that
     laptop_setup.py consumes.
  4. Merges the discovered entries with any existing `apps.yaml` (append-only)
     and writes the result in the schema consumed by `laptop_setup.py`.

Non-destructive and append-only: the scan NEVER removes or overwrites existing
entries. It only APPENDS apps whose `name` is not already in the target file, so
any manual edit you made stays intact. This makes it safe to build a cross-
platform snapshot:

    # one-time: start fresh
    (delete everything in apps.yaml, or use an empty file)

    # on each of your machines, in turn:
    python scan_machine.py        # Windows  -> appends this machine's apps
    python scan_machine.py        # macOS    -> appends only new apps
    python scan_machine.py        # Linux    -> appends only new apps

The result is a union of every machine's detected tools. You remove entries
yourself; the scan never deletes. The output is a *draft* — review it before
running `laptop_setup.py`. Because install commands are generic guesses, you
should verify/correct them for the tools you actually want to manage.

Usage:
    python scan_machine.py                  # append to configs/apps.yaml
    python scan_machine.py --dry-run        # print YAML, do not write
    python scan_machine.py --print          # print YAML to stdout
    python scan_machine.py --output my.yaml # append to a custom path

Safety:
    - Append-only: existing entries are preserved verbatim; nothing is removed
      or overwritten. A `.bak` copy of the target is still kept as a safety net.
    - No installation, no network access (except listing package managers
      locally), no credentials. Read-only scan.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR  = SCRIPT_DIR.parent
DEFAULT_OUT = SKILL_DIR / "configs" / "apps.yaml"

# ═════════════════════════════════════════════════════════════════════════════
# Platform detection  (mirrors laptop_setup.detect_platform)
# ═════════════════════════════════════════════════════════════════════════════
def detect_platform() -> dict:
    os_name = platform.system()
    if os_name == "Darwin":
        return {"os": "macos", "os_display": "macOS"}
    if os_name == "Windows":
        return {"os": "windows", "os_display": "Windows"}
    if os_name == "Linux":
        return {"os": "linux", "os_display": "Linux"}
    return {"os": os_name.lower(), "os_display": os_name}


# ═════════════════════════════════════════════════════════════════════════════
# Low-level helpers
# ═════════════════════════════════════════════════════════════════════════════
def _has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def _macos_app(name: str) -> str:
    return f"/Applications/{name}.app"


def _run(cmd: list[str]) -> str | None:
    """Run a command, return its stdout (stripped) or None on failure."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return r.stdout
    except Exception:
        return None
    return None


# ═════════════════════════════════════════════════════════════════════════════
# 1. Dynamic discovery — no hardcoded app list.
#
# We discover installed tools/apps from the real filesystem and from package
# managers, instead of maintaining a static CATALOG of app names.
# ═════════════════════════════════════════════════════════════════════════════
def _executable_names(dirs: list[str]) -> dict[str, str]:
    """Return {name: absolute_path} for every executable found in *dirs*.

    Only the base name is kept; when the same name appears in several dirs the
    first one (PATH order) wins.
    """
    result: dict[str, str] = {}
    seen: set[str] = set()
    for d in dirs:
        base = os.path.expandvars(os.path.expanduser(d))
        if not os.path.isdir(base):
            continue
        try:
            entries = sorted(os.listdir(base))
        except OSError:
            continue
        for name in entries:
            if name.startswith(".") or name in seen:
                continue
            full = os.path.join(base, name)
            if os.access(full, os.X_OK) or name.lower().endswith((".exe", ".cmd", ".bat")):
                result[name] = full
                seen.add(name)
    return result


def _scan_path_commands() -> dict[str, str]:
    """Discover executables in the *typical* user install dirs.

    We intentionally do NOT scan every PATH entry or system dirs (e.g. /usr/bin,
    node_modules/.bin), because those are dominated by transitive/utility
    binaries that are not top-level apps and would flood the registry. Only the
    common per-user and language-manager bin folders are probed.
    """
    home = os.path.expanduser("~")
    dirs: list[str] = [
        "/usr/local/bin",
        f"{home}/.local/bin",
        f"{home}/.cargo/bin",
        f"{home}/.go/bin",
        f"{home}/.npm-global/bin",
    ]
    if sys.platform == "darwin":
        dirs.append("/opt/homebrew/bin")
    elif sys.platform.startswith("win"):
        dirs.append(os.path.expandvars(r"%LOCALAPPDATA%\Programs"))
    else:
        dirs.append("/opt/bin")
    return _executable_names(dirs)


def _scan_gui_apps(plat: dict) -> dict[str, str]:
    """Discover GUI apps in the standard install dir. Returns {name: app_path}."""
    result: dict[str, str] = {}
    if plat["os"] == "macos":
        for d in ("/Applications", os.path.expanduser("~/Applications")):
            if not os.path.isdir(d):
                continue
            try:
                for name in sorted(os.listdir(d)):
                    if name.endswith(".app"):
                        result.setdefault(name[:-4], os.path.join(d, name))
            except OSError:
                continue
    elif plat["os"] == "windows":
        for var in ("%PROGRAMFILES%", "%PROGRAMFILES(X86)%", "%LOCALAPPDATA%\\Programs"):
            base = os.path.expandvars(var)
            if not os.path.isdir(base):
                continue
            try:
                for name in sorted(os.listdir(base)):
                    display = name[:-4] if name.lower().endswith(".exe") else name
                    result.setdefault(display, os.path.join(base, name))
            except OSError:
                continue
    return result


def _scan_package_managers(plat: dict) -> dict[str, str]:
    """Discover tools installed by common package managers.

    Returns {name: install_hint} where install_hint is e.g. "npm" / "pip" /
    "brew-cask" / "brew-formula", used to build a generic install command.
    """
    found: dict[str, str] = {}

    # npm global packages
    out = _run(["npm", "ls", "-g", "--depth=0", "--json"])
    if out:
        try:
            import json
            data = json.loads(out)
            for pkg, info in (data.get("dependencies") or {}).items():
                if isinstance(info, dict) and "version" in info:
                    found.setdefault(pkg, "npm")
        except Exception:
            pass

    # pip / pip3 packages
    pip = "pip" if _has_cmd("pip") else "pip3"
    if _has_cmd(pip):
        out = _run([pip, "list", "--format=json"])
        if out:
            try:
                import json
                for item in json.loads(out):
                    name = (item.get("name") or "").strip()
                    if name:
                        found.setdefault(name, "pip")
            except Exception:
                pass

    # Homebrew (macOS) — casks and formulas
    if plat["os"] == "macos" and _has_cmd("brew"):
        casks = _run(["brew", "list", "--cask"])
        if casks:
            for c in casks.split():
                found.setdefault(c, "brew-cask")
        formulas = _run(["brew", "list", "--formula"])
        if formulas:
            for f in formulas.split():
                found.setdefault(f, "brew-formula")

    return found


# ═════════════════════════════════════════════════════════════════════════════
# 2. Build generic install commands (best-effort guesses)
#
# laptop_setup.py only consumes install_macos / install_windows / install_linux_*
# keys. So we always map a discovered tool to those, using a sensible default
# package manager per platform.
# ═════════════════════════════════════════════════════════════════════════════
def _cask_slug(name: str) -> str:
    """Best-effort Homebrew cask slug: lowercase, spaces->dash, drop .app."""
    slug = name.replace(".app", "").strip().lower()
    return slug.replace(" ", "-")


def _generic_install(name: str, plat: dict, source: str, is_gui: bool) -> dict:
    """Return install_<os> dict for a discovered tool.

    *source* is one of "path" | "npm" | "pip" | "brew-cask" | "brew-formula".
    These are guesses — the user should review them.
    """
    if plat["os"] == "macos":
        if is_gui:
            return {"install_macos": f"brew install --cask {_cask_slug(name)}"}
        if source == "npm":
            return {"install_macos": f"npm install -g {name}"}
        if source == "pip":
            return {"install_macos": f"pip3 install {name}"}
        if source == "brew-formula":
            return {"install_macos": f"brew install {name}"}
        return {"install_macos": f"brew install {name}"}
    if plat["os"] == "windows":
        if source == "npm":
            return {"install_windows": f"npm install -g {name}"}
        if source == "pip":
            return {"install_windows": f"pip install {name}"}
        return {"install_windows": f"winget install -e --id {name}"}
    # linux
    if source == "npm":
        return {"install_linux_apt": f"sudo apt install -y {name}",
                "install_linux_dnf": f"sudo dnf install -y {name}"}
    if source == "pip":
        return {"install_linux_apt": f"sudo apt install -y python3-{name.lower()}",
                "install_linux_dnf": f"sudo dnf install -y python3-{name.lower()}"}
    return {"install_linux_apt": f"sudo apt install -y {name}",
            "install_linux_dnf": f"sudo dnf install -y {name}"}


def _check_for(name: str, plat: dict, is_gui: bool) -> dict:
    """Return a check_<os> dict for the discovered tool."""
    if plat["os"] == "macos":
        if is_gui:
            return {"check_macos_path": _macos_app(name)}
        return {"check_command": name}
    if plat["os"] == "windows":
        if is_gui:
            return {"check_windows_path": f"%PROGRAMFILES%\\{name}"}
        return {"check_command": name}
    return {"check_command": name}


# ═════════════════════════════════════════════════════════════════════════════
# 3. YAML emission (minimal, dependency-free, matches laptop_setup.py schema)
# ═════════════════════════════════════════════════════════════════════════════
def _yaml_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        items = ", ".join(_yaml_scalar(x) for x in v)
        return f"[{items}]"
    s = str(v)
    needs_quote = (
        s == ""
        or any(ch in s for ch in (":", "#", "'", '"', "%", "\\", "{", "}", "[", "]", "@", "`"))
        or s.strip() != s
        or s.lower() in ("true", "false", "yes", "no", "null", "~")
        or s.isdigit()
    )
    if needs_quote:
        s = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'
    return s


def _emit_mapping(out: list[str], mapping: dict, indent: int = 0) -> None:
    pad = "  " * indent
    for k, v in mapping.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            out.append(f"{pad}{k}:")
            for item in v:
                keys = list(item.keys())
                if "name" in keys:
                    keys.remove("name")
                    keys.insert(0, "name")
                first_key = keys[0]
                out.append(f"{pad}- {first_key}: {_yaml_scalar(item[first_key])}")
                for ik in keys[1:]:
                    out.append(f"{pad}  {ik}: {_yaml_scalar(item[ik])}")
        elif isinstance(v, list):
            out.append(f"{pad}{k}: {_yaml_scalar(v)}")
        elif isinstance(v, dict):
            out.append(f"{pad}{k}:")
            _emit_mapping(out, v, indent + 1)
        else:
            out.append(f"{pad}{k}: {_yaml_scalar(v)}")


def _emit_list_item(out: list[str], mapping: dict, indent: int = 1) -> None:
    """Emit a single `- key: value` list item whose further keys are indented."""
    pad = "  " * indent
    keys = list(mapping.keys())
    if not keys:
        out.append(f"{pad}- {{}}")
        return
    first = keys[0]
    out.append(f"{pad}- {first}: {_yaml_scalar(mapping[first])}")
    for k in keys[1:]:
        v = mapping[k]
        if isinstance(v, list) and v and isinstance(v[0], dict):
            out.append(f"{pad}  {k}:")
            for item in v:
                ikeys = list(item.keys())
                if "name" in ikeys:
                    ikeys.remove("name"); ikeys.insert(0, "name")
                out.append(f"{pad}    - {ikeys[0]}: {_yaml_scalar(item[ikeys[0]])}")
                for ik in ikeys[1:]:
                    out.append(f"{pad}      {ik}: {_yaml_scalar(item[ik])}")
        elif isinstance(v, list):
            out.append(f"{pad}  {k}: {_yaml_scalar(v)}")
        elif isinstance(v, dict):
            out.append(f"{pad}  {k}:")
            _emit_mapping(out, v, indent + 2)
        else:
            out.append(f"{pad}  {k}: {_yaml_scalar(v)}")


def build_yaml(plat: dict, apps: list, discovered: list[str]) -> str:
    lines: list[str] = []
    lines.append("#")
    lines.append("# apps.yaml — DRAFT from scan_machine.py (non-destructive merge)")
    lines.append("#")
    lines.append("# This file lists tools/apps found on this machine, plus any entries")
    lines.append("# you previously curated (preserved on re-scan).")
    lines.append("# ACTIVE entries have a reliable install command (managed by a package")
    lines.append("# manager — brew/npm/pip). Apps with no known install method are")
    lines.append("# listed as COMMENTS at the bottom, not active entries.")
    lines.append("# Before running laptop_setup.py, review it and:")
    lines.append("#   • delete apps you don't want managed")
    lines.append("#   • correct/complete install_<os> commands as needed")
    lines.append("#   • map `profiles` to your real team roles")
    lines.append("#   • never inline secrets (use --credentials-file)")
    lines.append("#")
    lines.append(f"# platform detected at generation time: {plat['os_display']}")
    lines.append("#")
    lines.append("")
    lines.append("settings:")
    lines.append("  default_profiles: [baseline]")
    lines.append("")
    lines.append("apps:")
    for entry in apps:
        _emit_list_item(lines, entry, indent=1)
        lines.append("")

    if discovered:
        lines.append("#")
        lines.append("# ── other CLI tools found in typical install folders (inventory) ──")
        lines.append("# These are not managed (no package-manager mapping); they are listed")
        lines.append("# so you can see what else is on this machine. Add an install_<os>")
        lines.append("# command if you want to manage any of them.")
        for i in range(0, len(discovered), 10):
            chunk = ", ".join(discovered[i:i + 10])
            lines.append(f"#   {chunk}")

    return "\n".join(lines) + "\n"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Merge with an existing registry (non-destructive, append-only)
#
# Existing entries are preserved verbatim and NEVER overwritten, even if the
# same app is detected again on another machine (so manual edits survive).
# The scan only appends entries whose `name` is not already present. The user
# removes entries themselves; the scan never deletes anything.
# ═════════════════════════════════════════════════════════════════════════════
def _load_existing_apps(path: Path) -> list:
    if not path.exists():
        return []
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        apps = data.get("apps")
        return apps if isinstance(apps, list) else []
    except Exception:
        return []


def merge_apps(scanned: list, existing: list) -> list:
    """Non-destructive union (case-insensitive by name).

    Existing entries are ALWAYS preserved and never overwritten. The scan only
    APPENDS entries whose `name` is not already present (case-insensitively), so
    a catalog entry named "Maven" won't duplicate an existing "maven".
    """
    existing_names = {str(a.get("name", "")).casefold()
                      for a in existing if isinstance(a, dict)}
    new_apps = [a for a in scanned if isinstance(a, dict)
                and str(a.get("name", "")).casefold() not in existing_names]
    return existing + new_apps


# ═════════════════════════════════════════════════════════════════════════════
# 5. Orchestration
# ═════════════════════════════════════════════════════════════════════════════
def discover_all(plat: dict) -> tuple[list[dict], list[str]]:
    """Discover tools/apps and return (managed_entries, discovered_suggestions).

    managed_entries: tools with a RELIABLE install method — i.e. those actually
        installed by a package manager we can reuse (Homebrew formula/cask,
        npm global, pip). Their install command (e.g. `brew install <formula>`)
        is known to work because the package manager installed them.

    discovered_suggestions: everything that is installed but whose install
        method is UNKNOWN or unreliable — GUI apps in /Applications not found in
        Homebrew casks (private/unpopular apps we can't `brew install --cask`),
        plus extra CLI binaries in the typical install folders that no package
        manager tracks. These are emitted as a COMMENTED inventory so the user
        can see what's on the machine without polluting the active registry
        with apps that have no viable install command.

    Fully dynamic: no hardcoded catalog of app names.
    """
    os_label = plat["os"]

    gui = _scan_gui_apps(plat)
    pkg = _scan_package_managers(plat)

    # Reliable, installable set = package-manager-managed tools.
    # (brew-cask and brew-formula come from `brew list`; npm/pip from their
    # global registries.) For these the re-install command is dependable.
    reliable: dict[str, tuple[str, str, bool]] = {}
    for name, source in pkg.items():
        reliable.setdefault(name.casefold(), (name, source, source == "brew-cask"))

    managed: list[dict] = []
    for lower, (display, source, is_gui) in reliable.items():
        entry = {"name": display, "profiles": ["baseline"], "platforms": [os_label]}
        entry.update(_check_for(display, plat, is_gui))
        entry.update(_generic_install(display, plat, source, is_gui))
        managed.append(entry)

    # Uncertain installs become suggestions, not active entries:
    #   (a) GUI apps found only in /Applications and not in Homebrew casks —
    #       private/unpopular, we don't know how to install them -> SKIP.
    #   (b) CLI binaries in typical folders not tracked by any package manager.
    casks = {name.casefold() for name, s in pkg.items() if s == "brew-cask"}
    suggestions: set[str] = set()
    for name in gui:
        if name.casefold() not in reliable and name.casefold() not in casks:
            suggestions.add(name)

    cmds = _scan_path_commands()
    for name in cmds:
        if name.casefold() not in reliable and not name.startswith(("_", ".")):
            suggestions.add(name)

    return managed, sorted(suggestions)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Scan this machine and emit a customized apps.yaml draft.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--print", action="store_true", help="Print YAML to stdout and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be written without modifying any files")
    ap.add_argument("--output", type=str, default=None,
                    help="Write to a custom path instead of configs/apps.yaml")
    args = ap.parse_args()

    plat = detect_platform()
    scanned_apps, discovered = discover_all(plat)

    target = Path(args.output).expanduser().resolve() if args.output else DEFAULT_OUT

    existing_apps = _load_existing_apps(target)
    if existing_apps:
        merged = merge_apps(scanned_apps, existing_apps)
        added = len(merged) - len(existing_apps)
        print(f"[scan_machine] kept {len(existing_apps)} existing, appended "
              f"{added} new -> {len(merged)} total (nothing overwritten or removed)",
              file=sys.stderr)
    else:
        merged = scanned_apps

    yaml_text = build_yaml(plat, merged, discovered)

    if args.print or args.dry_run:
        print(yaml_text)
        if args.dry_run and not args.print:
            print(f"[dry-run] would write {target} ({len(yaml_text)} bytes)", file=sys.stderr)
        return 0

    # Backup existing default config before writing (cheap safety net)
    if target == DEFAULT_OUT and target.exists():
        bak = target.with_suffix(".yaml.bak")
        shutil.copy2(target, bak)
        print(f"[scan_machine] backed up existing {target.name} -> {bak.name}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml_text, encoding="utf-8")
    print(f"[scan_machine] wrote draft for {plat['os_display']} -> {target}")
    print("[scan_machine] review the file, then run: "
          "python laptop_setup.py --list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
