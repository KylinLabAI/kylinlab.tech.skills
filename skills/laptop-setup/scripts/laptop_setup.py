#!/usr/bin/env python3
"""
laptop_setup.py – Cross-platform laptop setup tool.

Detects platform & architecture, checks which daily-use apps are already
installed, and installs the missing ones from apps.yaml.

Usage:
    python laptop_setup.py                 # list apps & status (default)
    python laptop_setup.py --info          # show platform / arch / chip info
    python laptop_setup.py --list          # list apps with install status
    python laptop_setup.py --profiles      # list configured app profiles
    python laptop_setup.py --list --profile baseline
    python laptop_setup.py --check         # like --list but exit 1 if missing
    python laptop_setup.py --install       # install all missing apps
    python laptop_setup.py --install --profile baseline --dry-run
    python laptop_setup.py --install --name UTM   # install one specific app
    python laptop_setup.py --install --dry-run     # preview only
    python laptop_setup.py --verify        # verify simulators/emulators & post-install state
    python laptop_setup.py --verify --name Xcode   # verify one specific app
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ═════════════════════════════════════════════════════════════════════════════
# Paths
# ═════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR  = SCRIPT_DIR.parent
CONFIG     = SKILL_DIR / "configs" / "apps.yaml"

# ═════════════════════════════════════════════════════════════════════════════
# Colours  (auto-disabled on dumb terminals / NO_COLOR / vanilla Windows)
# ═════════════════════════════════════════════════════════════════════════════
_NO_COLOR = os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb"

if sys.platform == "win32" and not _NO_COLOR:
    try:
        import ctypes
        _h = ctypes.windll.kernel32.GetStdHandle(-11)
        ctypes.windll.kernel32.SetConsoleMode(_h, 7)
    except Exception:
        _NO_COLOR = True


def _c(code: str, text: str) -> str:
    return text if _NO_COLOR else f"\033[{code}m{text}\033[0m"


def green(t: str) -> str:  return _c("32", t)
def red(t: str) -> str:    return _c("31", t)
def yellow(t: str) -> str: return _c("33", t)
def bold(t: str) -> str:   return _c("1", t)
def dim(t: str) -> str:    return _c("2", t)


TAG = _c("36;1", "[laptop-setup]")


def info(m: str)  -> None: print(f"{TAG} {m}")
def ok(m: str)    -> None: print(f"{TAG} {green('✓')} {m}")
def warn(m: str)  -> None: print(f"{TAG} {yellow('⚠')} {m}")
def fail(m: str)  -> None: print(f"{TAG} {red('✗')} {m}")

# ═════════════════════════════════════════════════════════════════════════════
# Minimal YAML parser  (no external dependency required)
# ═════════════════════════════════════════════════════════════════════════════
# The apps.yaml schema is intentionally flat (no nested dicts) so this
# simple parser handles everything we need.  Falls back to PyYAML if present.


def _pval(v: str):
    """Parse a scalar YAML value."""
    v = v.strip()
    if not v:
        return None
    lo = v.lower()
    if lo in ("true", "yes"):
        return True
    if lo in ("false", "no"):
        return False
    if v.startswith("[") and v.endswith("]"):
        return [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    try:
        return int(v)
    except ValueError:
        pass
    return v


def _load_config(path: str | Path) -> dict:
    """Load apps.yaml – prefers PyYAML, falls back to built-in parser."""
    try:
        import yaml  # type: ignore
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        pass
    return _parse_flat_yaml(path)


def _parse_flat_yaml(path: str | Path) -> dict:
    """Built-in parser for the flat key-value YAML used in apps.yaml.

    Supports:
      - top-level keys:  settings, apps
      - flat scalar values, inline lists [a, b, c]
      - block-style list values (lines starting with '- ')
        - string items:  - "some command"
        - dict items:    - label: "foo"  /  command: "bar"
    """
    with open(path, encoding="utf-8") as f:
        raw = f.read()

    result: dict = {}
    top_key: str | None = None
    cur: dict | None = None  # current app being built
    list_key: str | None = None  # key accumulating block-style list items
    list_item: dict | None = None  # current dict item inside a block list

    for raw_line in raw.split("\n"):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # strip trailing inline comments (not inside quotes)
        ci = stripped.find("  #")
        if ci > 0 and stripped[:ci].count('"') % 2 == 0:
            stripped = stripped[:ci].rstrip()

        indent = len(raw_line) - len(raw_line.lstrip())

        # ── top-level key ──
        if indent == 0 and ":" in stripped:
            list_key = None
            list_item = None
            k, v = stripped.split(":", 1)
            k, v = k.strip(), v.strip()
            top_key = k
            if v:
                result[k] = _pval(v)
            elif k == "apps":
                result[k] = []
            else:
                result[k] = {}
            cur = None
            continue

        # ── settings block ──
        if top_key == "settings" and isinstance(result.get("settings"), dict):
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                result["settings"][k.strip()] = _pval(v)
            continue

        # ── apps list ──
        if top_key == "apps" and isinstance(result.get("apps"), list):
            # New app item  (top-level "- name: ...")
            if stripped.startswith("- ") and indent <= 4 and ":" in stripped[2:]:
                list_key = None
                list_item = None
                cur = {}
                result["apps"].append(cur)
                rest = stripped[2:].strip()
                if rest and ":" in rest:
                    k, v = rest.split(":", 1)
                    cur[k.strip()] = _pval(v)
            # Block-style list item  (  - "some command" or  - label: "foo")
            elif stripped.startswith("- ") and list_key and cur is not None:
                rest = stripped[2:].strip()
                # Quoted string item:  - "some command" or - 'some command'
                if rest and rest[0] in "\"'":
                    list_item = None
                    val = rest.strip("\"'")
                    if isinstance(cur.get(list_key), list):
                        cur[list_key].append(val)
                # Dict item:  - label: value
                elif ":" in rest:
                    k, v = rest.split(":", 1)
                    k, v = k.strip(), v.strip()
                    if v:
                        list_item = {k: _pval(v)}
                        if isinstance(cur.get(list_key), list):
                            cur[list_key].append(list_item)
                    else:
                        list_item = {k: None}
                        if isinstance(cur.get(list_key), list):
                            cur[list_key].append(list_item)
                else:
                    # Unquoted string item
                    list_item = None
                    if isinstance(cur.get(list_key), list):
                        cur[list_key].append(rest)
            # Continuation of a dict item inside a list  (  command: "bar")
            elif list_item is not None and list_key and cur is not None and ":" in stripped:
                k, v = stripped.split(":", 1)
                k, v = k.strip(), v.strip()
                if v:
                    list_item[k] = _pval(v)
            # Regular key: value
            elif cur is not None and ":" in stripped:
                k, v = stripped.split(":", 1)
                k, v = k.strip(), v.strip()
                list_item = None
                if v:
                    cur[k] = _pval(v)
                    list_key = None
                else:
                    # Empty value — next lines may be block list items
                    cur[k] = []
                    list_key = k
            continue

    return result

# ═════════════════════════════════════════════════════════════════════════════
# Platform & Architecture Detection
# ═════════════════════════════════════════════════════════════════════════════
_ARCH_MAP = {
    "x86_64": "x64", "AMD64": "x64",
    "aarch64": "arm64", "arm64": "arm64",
    "i386": "x86", "i686": "x86",
}


def detect_platform() -> dict:
    """Return dict with os, os_display, arch, arch_label, chip."""
    os_name  = platform.system()         # Darwin / Windows / Linux
    arch_raw = platform.machine()        # arm64 / x86_64 / AMD64
    chip     = arch_raw

    if os_name == "Darwin":
        os_label = "macos"
        ver = platform.mac_ver()[0]
        os_display = f"macOS {ver}" if ver else "macOS"
        try:
            r = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                chip = r.stdout.strip()
        except Exception:
            pass

    elif os_name == "Windows":
        os_label = "windows"
        os_display = f"Windows {platform.version()}"

    elif os_name == "Linux":
        os_label = "linux"
        os_display = "Linux"
        try:
            with open("/etc/os-release") as fp:
                for ln in fp:
                    if ln.startswith("PRETTY_NAME="):
                        os_display = ln.split("=", 1)[1].strip().strip('"')
                        break
        except Exception:
            pass

    else:
        os_label = os_name.lower()
        os_display = os_name

    arch_label = _ARCH_MAP.get(arch_raw, arch_raw)
    return dict(
        os=os_label, os_display=os_display,
        arch=arch_raw, arch_label=arch_label, chip=chip,
    )


def detect_pkg_managers() -> set[str]:
    """Return names of available package managers."""
    found: set[str] = set()
    for name in ("brew", "winget", "choco", "scoop",
                 "apt", "dnf", "snap", "pacman", "mas"):
        if shutil.which(name):
            found.add(name)
    return found


def ensure_package_manager(plat: dict, *, dry_run: bool = False) -> bool:
    """Install primary package manager if missing. Return True if ready."""
    os_l = plat["os"]

    if os_l == "macos" and not shutil.which("brew"):
        if dry_run:
            info("  Would install Homebrew because brew is not on PATH")
            return True
        info("Homebrew not found — installing …")
        cmd = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        subprocess.run(cmd, shell=True, check=True)
        # Ensure brew is on PATH for Apple Silicon
        for p in ("/opt/homebrew/bin", "/usr/local/bin"):
            if os.path.isdir(p) and p not in os.environ.get("PATH", ""):
                os.environ["PATH"] = f"{p}:{os.environ['PATH']}"
        if not ensure_homebrew_shellenv(dry_run=dry_run):
            warn("Homebrew installed, but updating ~/.zprofile with brew shellenv failed.")
        return True

    if os_l == "windows" and not shutil.which("winget"):
        warn("winget not found — install 'App Installer' from the Microsoft Store.")
        return False

    if os_l == "linux":
        if not any(shutil.which(pm) for pm in ("apt", "dnf", "snap", "pacman")):
            warn("No supported package manager found (apt / dnf / snap / pacman).")
            return False

    return True


def ensure_homebrew_shellenv(*, dry_run: bool = False) -> bool:
    """Persist Homebrew shellenv in ~/.zprofile after bootstrapping brew."""
    cmd = (
        "touch ~/.zprofile && grep -q 'brew shellenv' ~/.zprofile 2>/dev/null || "
        "{ test -x /opt/homebrew/bin/brew && "
        "echo 'eval \"$(/opt/homebrew/bin/brew shellenv)\"' >> ~/.zprofile || "
        "test -x /usr/local/bin/brew && "
        "echo 'eval \"$(/usr/local/bin/brew shellenv)\"' >> ~/.zprofile; }"
    )
    if dry_run:
        info(f"  Would ensure Homebrew shellenv in ~/.zprofile: {cmd}")
        return True
    try:
        r = subprocess.run(cmd, shell=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False

# ═════════════════════════════════════════════════════════════════════════════
# App Detection
# ═════════════════════════════════════════════════════════════════════════════

def list_value(value) -> list[str]:
    """Normalize a scalar or list config value to a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def shell_ok(command: str, *, timeout: int = 10) -> bool:
    """Return True when a shell check command exits successfully."""
    try:
        return subprocess.run(
            command,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        ).returncode == 0
    except Exception:
        return False


def is_installed(app: dict, os_label: str) -> tuple[bool, str]:
    """Check whether *app* is already installed. Return (found, detail)."""

    # 1. Shell checks, e.g. check_shell or check_macos_shell
    for sk in (f"check_{os_label}_shell", "check_shell"):
        for cmd in list_value(app.get(sk)):
            if shell_ok(cmd):
                return True, f"Shell check passed: {cmd}"

    # 2. Path checks, e.g. check_macos_path, check_macos_paths, or check_path
    for pk in (f"check_{os_label}_path", f"check_{os_label}_paths", "check_path", "check_paths"):
        for raw_path in list_value(app.get(pk)):
            p = os.path.expandvars(os.path.expanduser(str(raw_path)))
            if os.path.exists(p):
                return True, f"Found at {p}"

    # 3. Command checks, e.g. check_linux_command, check_command, or check_commands
    for ck in (f"check_{os_label}_command", f"check_{os_label}_commands", "check_command", "check_commands"):
        for cmd in list_value(app.get(ck)):
            if shutil.which(cmd):
                return True, f"Command '{cmd}' on PATH"

    return False, "Not installed"

# ═════════════════════════════════════════════════════════════════════════════
# Install Logic
# ═════════════════════════════════════════════════════════════════════════════

def get_install_cmd(app: dict, os_label: str, managers: set[str]) -> tuple[str | None, str]:
    """Return (shell_command, method_label) or (None, reason)."""
    # Direct platform key  (install_macos, install_windows)
    dk = f"install_{os_label}"
    if dk in app:
        return app[dk], os_label

    # Linux package-manager variants
    if os_label == "linux":
        for pm in ("apt", "dnf", "snap", "pacman"):
            pk = f"install_linux_{pm}"
            if pk in app and pm in managers:
                return app[pk], pm
        ck = "install_linux_custom"
        if ck in app:
            return app[ck], "custom"

    return None, "no install method"


def install_app(
    app: dict, os_label: str, managers: set[str], *, dry_run: bool = False,
) -> tuple[bool, str]:
    """Install a single app. Return (success, message)."""
    cmd, method = get_install_cmd(app, os_label, managers)
    if cmd is None:
        return False, f"No install method ({method})"

    if dry_run:
        info(f"  Would run: {cmd}")
        return True, "dry-run"

    info(f"  Running: {dim(cmd)}")
    try:
        r = subprocess.run(cmd, shell=True, timeout=600)
        if r.returncode == 0:
            return True, "Installed successfully"
        return False, f"Exit code {r.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Timed out (10 min)"
    except Exception as exc:
        return False, str(exc)


def get_post_install_cmds(app: dict, os_label: str) -> list[str]:
    """Return list of post-install commands for the current platform."""
    cmds: list[str] = []
    # post_install_<os> can be a single string or a list of strings
    pk = f"post_install_{os_label}"
    raw = app.get(pk)
    if raw is None:
        return cmds
    if isinstance(raw, str):
        cmds = [raw]
    elif isinstance(raw, list):
        cmds = [str(c) for c in raw]
    return cmds


# ═════════════════════════════════════════════════════════════════════════════════════════
# Configuration steps  (post-install configuration with optional credentials)
# ═════════════════════════════════════════════════════════════════════════════════════════
def get_configure_steps(app: dict, os_label: str) -> list[dict]:
    """Return list of configure step dicts for the current platform.

    Each step dict may contain:
      - name            : human-readable label
      - check           : optional shell expr; if exit 0, step is skipped
      - interactive     : shell command run in the user's TTY (may prompt)
      - non_interactive : shell command run with credentials in subprocess env
      - requires        : list of credential keys needed for non_interactive
      - sensitive       : bool; mask the command in console output
    """
    pk = f"configure_{os_label}"
    raw = app.get(pk)
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, dict) and (
            "interactive" in item or "non_interactive" in item
        ):
            out.append(item)
    return out


def _load_yaml_generic(path: str | Path) -> dict:
    """Load any YAML file. Prefer PyYAML, else use a minimal fallback.

    The fallback supports a flat top-level mapping and one level of nesting:
        KEY: value
        "App Name":
          KEY: value
    Comments and blank lines are ignored.
    """
    try:
        import yaml  # type: ignore
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
    except ImportError:
        pass
    result: dict = {}
    cur_key: str | None = None
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            stripped = line.strip()
            if ":" not in stripped:
                continue
            k, v = stripped.split(":", 1)
            k = k.strip().strip('"').strip("'")
            v = v.strip()
            if indent == 0:
                if v == "":
                    result[k] = {}
                    cur_key = k
                else:
                    result[k] = v.strip('"').strip("'")
                    cur_key = None
            else:
                if cur_key is None:
                    continue
                target = result.get(cur_key)
                if not isinstance(target, dict):
                    result[cur_key] = target = {}
                target[k] = v.strip('"').strip("'")
    return result


def load_credentials(path: str | Path | None) -> dict:
    """Load a credentials YAML file.

    Returns a dict with two sub-namespaces:
      {
        "_global": {KEY: value, ...},
        "<app name>": {KEY: value, ...},
      }

    A flat top-level KEY: value pair goes into ``_global``.
    A mapping under an app name overrides ``_global`` for that app.
    """
    if not path:
        return {"_global": {}}
    p = Path(path).expanduser().resolve()
    if not p.exists():
        fail(f"Credentials file not found: {p}")
        return {"_global": {}}
    # Warn about world-readable credentials files on POSIX
    try:
        mode = p.stat().st_mode & 0o777
        if sys.platform != "win32" and mode & 0o077:
            warn(
                f"Credentials file {p} is mode {mode:o}; "
                f"recommended: chmod 600 \"{p}\""
            )
    except Exception:
        pass
    raw = _load_yaml_generic(p)
    result: dict = {"_global": {}}
    for k, v in raw.items():
        if isinstance(v, dict):
            result[k] = {str(kk): str(vv) for kk, vv in v.items()}
        else:
            result["_global"][str(k)] = str(v)
    return result


def resolve_credentials(
    app_name: str, requires: list[str], creds: dict,
) -> tuple[dict, list[str]]:
    """Resolve required credential keys for an app.

    Lookup order per key: app-scoped → _global → environment variable.
    Returns (env_overlay, missing_keys).
    """
    env_overlay: dict = {}
    missing: list[str] = []
    app_scope = creds.get(app_name, {}) if isinstance(creds.get(app_name), dict) else {}
    g = creds.get("_global", {}) if isinstance(creds.get("_global"), dict) else {}
    for key in requires:
        if key in app_scope:
            env_overlay[key] = str(app_scope[key])
        elif key in g:
            env_overlay[key] = str(g[key])
        elif key in os.environ and os.environ[key]:
            env_overlay[key] = os.environ[key]
        else:
            missing.append(key)
    return env_overlay, missing


def _mask_secrets(text: str, secret_values: list[str]) -> str:
    for s in secret_values:
        if s and len(s) >= 4:
            text = text.replace(s, "****")
    return text


def run_configure(
    app: dict,
    os_label: str,
    creds: dict,
    *,
    non_interactive_only: bool = False,
    dry_run: bool = False,
) -> tuple[bool, list[dict]]:
    """Run configure steps for an app.

    Returns (all_ok, results) where each result is
        {name, mode, status, detail, missing}.
    Modes: 'non_interactive', 'interactive', 'skipped', 'unavailable'.
    Statuses: 'ok', 'fail', 'skipped', 'dry-run', 'missing-creds'.
    """
    steps = get_configure_steps(app, os_label)
    if not steps:
        return True, []
    app_name = app.get("name", "?")
    results: list[dict] = []
    all_ok = True
    info(f"  Running {len(steps)} configure step(s) …")
    for i, step in enumerate(steps, 1):
        step_name = step.get("name") or f"step {i}"
        check_cmd = step.get("check")
        interactive_cmd = step.get("interactive")
        non_interactive_cmd = step.get("non_interactive")
        requires = step.get("requires") or []
        if not isinstance(requires, list):
            requires = [str(requires)]
        sensitive = bool(step.get("sensitive"))

        # Skip step if check passes
        if check_cmd and not dry_run:
            try:
                r = subprocess.run(check_cmd, shell=True, timeout=30)
                if r.returncode == 0:
                    info(f"  [{i}/{len(steps)}] {dim(step_name)}  (already configured)")
                    results.append(dict(
                        name=step_name, mode="skipped", status="skipped",
                        detail="check passed; step skipped", missing=[],
                    ))
                    continue
            except Exception:
                pass

        # Pick mode
        env_overlay, missing = resolve_credentials(app_name, requires, creds)
        can_non_interactive = bool(non_interactive_cmd) and not missing
        if can_non_interactive:
            mode = "non_interactive"
            cmd = non_interactive_cmd
        elif non_interactive_only:
            fail(f"  [{i}/{len(steps)}] {step_name}: missing credentials {missing}")
            results.append(dict(
                name=step_name, mode="unavailable", status="missing-creds",
                detail=f"required: {missing}", missing=missing,
            ))
            all_ok = False
            continue
        elif interactive_cmd:
            mode = "interactive"
            cmd = interactive_cmd
        else:
            warn(f"  [{i}/{len(steps)}] {step_name}: no usable command (creds missing for non_interactive)")
            results.append(dict(
                name=step_name, mode="unavailable", status="missing-creds",
                detail=f"required: {missing}", missing=missing,
            ))
            all_ok = False
            continue

        # Echo command (masked if sensitive)
        secret_values = list(env_overlay.values()) if sensitive else []
        shown = _mask_secrets(cmd, secret_values) if sensitive else cmd
        info(f"  [{i}/{len(steps)}] {bold(step_name)} — mode={mode}")
        info(f"        {dim(shown)}")

        if dry_run:
            results.append(dict(
                name=step_name, mode=mode, status="dry-run",
                detail="would run", missing=[],
            ))
            continue

        env = os.environ.copy()
        env.update(env_overlay)
        try:
            r = subprocess.run(cmd, shell=True, env=env, timeout=900)
            if r.returncode == 0:
                ok(f"        {step_name}: ok")
                results.append(dict(
                    name=step_name, mode=mode, status="ok",
                    detail="completed", missing=[],
                ))
            else:
                fail(f"        {step_name}: exit {r.returncode}")
                results.append(dict(
                    name=step_name, mode=mode, status="fail",
                    detail=f"exit {r.returncode}", missing=[],
                ))
                all_ok = False
        except subprocess.TimeoutExpired:
            fail(f"        {step_name}: timed out")
            results.append(dict(
                name=step_name, mode=mode, status="fail",
                detail="timeout", missing=[],
            ))
            all_ok = False
        except Exception as exc:
            fail(f"        {step_name}: {exc}")
            results.append(dict(
                name=step_name, mode=mode, status="fail",
                detail=str(exc), missing=[],
            ))
            all_ok = False
    return all_ok, results


def get_verify_checks(app: dict, os_label: str) -> list[dict]:
    """Return list of {label, command} verification checks for the current platform."""
    pk = f"verify_{os_label}"
    raw = app.get(pk)
    if raw is None:
        return []
    if isinstance(raw, list):
        return [c for c in raw if isinstance(c, dict) and "label" in c and "command" in c]
    return []


def run_verify(app: dict, os_label: str) -> tuple[bool, list[dict]]:
    """Run verification checks for an app. Return (all_ok, results).

    Each result: {label, command, output, ok}.
    """
    checks = get_verify_checks(app, os_label)
    if not checks:
        return True, []
    results: list[dict] = []
    all_ok = True
    for chk in checks:
        label, cmd = chk["label"], chk["command"]
        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30,
            )
            out = (r.stdout.strip() or r.stderr.strip() or "(no output)")
            ok_flag = r.returncode == 0
        except subprocess.TimeoutExpired:
            out = "(timed out)"
            ok_flag = False
        except Exception as exc:
            out = str(exc)
            ok_flag = False
        if not ok_flag:
            all_ok = False
        results.append(dict(label=label, command=cmd, output=out, ok=ok_flag))
    return all_ok, results


def run_post_install(
    app: dict, os_label: str, *, dry_run: bool = False,
) -> tuple[bool, list[str]]:
    """Run post-install steps for an app. Return (all_ok, messages)."""
    cmds = get_post_install_cmds(app, os_label)
    if not cmds:
        return True, []
    msgs: list[str] = []
    all_ok = True
    info(f"  Running {len(cmds)} post-install step(s) …")
    for i, cmd in enumerate(cmds, 1):
        if dry_run:
            info(f"  [{i}/{len(cmds)}] Would run: {cmd}")
            msgs.append(f"dry-run: {cmd}")
            continue
        info(f"  [{i}/{len(cmds)}] {dim(cmd)}")
        try:
            r = subprocess.run(cmd, shell=True, timeout=600)
            if r.returncode == 0:
                msgs.append(f"OK: {cmd}")
            else:
                msgs.append(f"FAIL (exit {r.returncode}): {cmd}")
                all_ok = False
        except subprocess.TimeoutExpired:
            msgs.append(f"TIMEOUT: {cmd}")
            all_ok = False
        except Exception as exc:
            msgs.append(f"ERROR ({exc}): {cmd}")
            all_ok = False
    return all_ok, msgs


def available_profiles(apps: list[dict]) -> list[str]:
    """Return sorted profile names declared by the app registry."""
    profiles: set[str] = set()
    for app in apps:
        profiles.update(list_value(app.get("profiles")))
    return sorted(profiles)


def select_apps(apps: list[dict], args: argparse.Namespace) -> list[dict]:
    """Apply optional name/profile filters while keeping default behavior broad."""
    selected = list(apps)

    if args.name:
        needle = args.name.lower()
        selected = [a for a in selected if needle in a.get("name", "").lower()]

    requested_profiles = set(args.profile or [])
    if requested_profiles and not args.all_profiles:
        selected = [
            a for a in selected
            if requested_profiles.intersection(set(list_value(a.get("profiles"))))
        ]

    return selected


def profile_label(args: argparse.Namespace) -> str:
    """Return display text for the active profile selection."""
    if args.all_profiles:
        return "all profiles"
    if args.profile:
        return ", ".join(args.profile)
    return "all apps"


# ═════════════════════════════════════════════════════════════════════════════
# Run summary
# ═════════════════════════════════════════════════════════════════════════════
def _summarize_phase(phase: dict | None) -> str:
    """Build a short status string for one phase block in a summary record."""
    if not phase:
        return dim("—")
    st = phase.get("status")
    if st == "ok":
        return green("ok")
    if st == "fail":
        return red("fail")
    return dim(str(st or "?"))


def _print_run_summary(records: list[dict]) -> None:
    """Print a unified summary of install + post-install + configure outcomes."""
    if not records:
        return
    print()
    info(bold("Run summary"))
    info(f"{'App':<28} {'Install':<10} {'Post-install':<14} {'Configure':<12}")
    info(f"{'─' * 28} {'─' * 10} {'─' * 14} {'─' * 12}")
    for rec in records:
        name = rec.get("name", "?")
        inst = _summarize_phase(rec.get("install"))
        post = _summarize_phase(rec.get("post_install"))
        cfg  = _summarize_phase(rec.get("configure"))
        info(f"{name:<28} {inst:<19} {post:<23} {cfg:<21}")

    # Highlight missing credentials & failed configure steps
    print()
    notes: list[str] = []
    for rec in records:
        cfg_block = rec.get("configure") or {}
        for step in cfg_block.get("steps", []):
            if step.get("status") == "missing-creds":
                notes.append(
                    f"  • {rec['name']} → {step['name']}: "
                    f"missing credentials {step.get('missing') or []}"
                )
            elif step.get("status") == "fail":
                notes.append(
                    f"  • {rec['name']} → {step['name']}: "
                    f"failed ({step.get('detail') or ''})"
                )
    if notes:
        warn("Manual follow-ups needed:")
        for n in notes:
            info(n)
        print()


def _write_run_summary_json(records: list[dict], plat: dict) -> None:
    """Persist machine-readable summary to ~/.laptop-setup/last-run.json (mode 600)."""
    if not records:
        return
    try:
        import json
        import datetime
        out_dir = Path.home() / ".laptop-setup"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "last-run.json"
        payload = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "platform":  plat,
            "records":   records,
        }
        out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        try:
            if sys.platform != "win32":
                out_path.chmod(0o600)
        except Exception:
            pass
        info(f"Wrote run summary: {dim(str(out_path))}")
    except Exception as exc:
        warn(f"Could not write run summary JSON: {exc}")


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Laptop Setup — detect platform & install daily-use apps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s --info                Show platform / arch / chip
  %(prog)s --profiles            List configured app profiles
  %(prog)s --list                List apps with install status
  %(prog)s --list --profile baseline
  %(prog)s --check               Like --list but exit 1 if any missing
  %(prog)s --install             Install all missing apps
  %(prog)s --install --profile baseline --dry-run
  %(prog)s --install --name UTM  Install one specific app
  %(prog)s --install --dry-run   Preview commands only
""",
    )
    ap.add_argument("--info",    action="store_true", help="Show platform info")
    ap.add_argument("--list",    action="store_true", help="List apps & status")
    ap.add_argument("--check",   action="store_true", help="Like --list; exit 1 if missing")
    ap.add_argument("--install", action="store_true", help="Install missing apps")
    ap.add_argument("--setup",   action="store_true", help="Run post-install setup for already-installed apps")
    ap.add_argument("--configure", action="store_true", help="Run configure steps for already-installed apps")
    ap.add_argument("--verify",  action="store_true", help="Verify simulators/emulators & post-install state")
    ap.add_argument("--name",    type=str,            help="Target a specific app by name")
    ap.add_argument("--profile", action="append", default=[], help="Target apps in a profile; can be repeated")
    ap.add_argument("--all-profiles", action="store_true", help="Ignore profile filtering when combined with --profile")
    ap.add_argument("--profiles", action="store_true", help="List configured app profiles")
    ap.add_argument("--dry-run", action="store_true", help="Preview commands only")
    ap.add_argument("--apps-file", type=str, default=None,
                    help="Path to an alternate apps.yaml (defaults to bundled configs/apps.yaml)")
    ap.add_argument("--credentials-file", type=str, default=None,
                    help="Path to a YAML file with credentials for non-interactive configure")
    ap.add_argument("--non-interactive", action="store_true",
                    help="Refuse interactive configure steps; require credentials")
    ap.add_argument("--skip-configure", action="store_true",
                    help="Skip configure steps during --install")
    args = ap.parse_args()

    # Default action: --list
    if not any((args.info, args.list, args.check, args.install, args.setup,
                args.configure, args.verify, args.profiles)):
        args.list = True

    # ── detect platform ──────────────────────────────────────────────────
    plat     = detect_platform()
    managers = detect_pkg_managers()

    # Always print platform header when showing info or installing
    if args.info or args.install:
        print()
        info(f"Platform:      {bold(plat['os_display'])}")
        info(f"Architecture:  {bold(plat['arch'])} ({plat['arch_label']})")
        info(f"Chip:          {bold(plat['chip'])}")
        info(f"Pkg managers:  {', '.join(sorted(managers)) or 'none detected'}")
        print()

    # ── load config ──────────────────────────────────────────────────────
    config_path = Path(args.apps_file).expanduser().resolve() if args.apps_file else CONFIG
    if not config_path.exists():
        fail(f"Config not found: {config_path}")
        return 1
    if args.apps_file:
        info(f"Apps file:     {bold(str(config_path))}")

    cfg  = _load_config(str(config_path))
    apps = cfg.get("apps") or []
    if not apps:
        warn("No apps defined in config")
        return 0

    if args.profiles:
        print()
        info("Profiles:")
        for profile in available_profiles(apps):
            info(f"  • {profile}")
        print()

    if args.info and not (args.list or args.check or args.install or args.setup or args.configure or args.verify or args.profiles):
        return 0
    if args.profiles and not (args.list or args.check or args.install or args.setup or args.configure or args.verify):
        return 0

    apps = select_apps(apps, args)
    if not apps:
        if args.name:
            fail(f"No app matching '{args.name}' with profile selection '{profile_label(args)}'")
        else:
            fail(f"No apps match profile selection '{profile_label(args)}'")
        return 1

    # ── load credentials (optional) ──────────────────────────────────
    creds: dict = {"_global": {}}
    if args.credentials_file:
        creds = load_credentials(args.credentials_file)
        n_global = len(creds.get("_global", {}))
        n_scoped = sum(1 for k, v in creds.items() if k != "_global" and isinstance(v, dict))
        info(f"Credentials:  loaded {n_global} global key(s), {n_scoped} app-scoped section(s)")

    # Aggregated summary records collected across phases
    summary_records: list[dict] = []

    # ── scan installed status ────────────────────────────────────────────
    rows: list[dict] = []
    for app in apps:
        name      = app.get("name", "?")
        platforms = app.get("platforms") or []
        applicable = plat["os"] in platforms

        if applicable:
            inst, detail = is_installed(app, plat["os"])
        else:
            inst = None
            detail = f"Not for {plat['os_display']} ({', '.join(platforms)} only)"

        rows.append(dict(
            app=app, name=name,
            applicable=applicable, installed=inst, detail=detail,
        ))

    # ── list / check ─────────────────────────────────────────────────────
    if args.list or args.check:
        print()
        info(f"Platform: {bold(plat['os_display'])}  "
             f"Arch: {bold(plat['arch'])} ({plat['arch_label']})  "
             f"Chip: {bold(plat['chip'])}")
        info(f"Selection: {profile_label(args)}")
        print()
        info(f"{'App':<28} {'Status':<15} {'Detail'}")
        info(f"{'─' * 28} {'─' * 15} {'─' * 42}")

        missing = 0
        for r in rows:
            if r["installed"] is None:
                st = dim("N/A")
                dt = dim(r["detail"])
            elif r["installed"]:
                st = green("Installed")
                dt = dim(r["detail"])
            else:
                st = red("Missing")
                dt = r["detail"]
                missing += 1
            # ANSI escapes add ~9 characters; pad extra to align
            info(f"{r['name']:<28} {st:<24} {dt}")

        n_applicable = sum(1 for r in rows if r["applicable"])
        n_installed  = sum(1 for r in rows if r["installed"] is True)
        print()
        info(f"Total: {len(rows)}  |  "
             f"Applicable: {n_applicable}  |  "
             f"Installed: {green(str(n_installed))}  |  "
             f"Missing: {red(str(missing)) if missing else '0'}")
        print()
        return 1 if args.check and missing else 0

    # ── install ──────────────────────────────────────────────────────────
    if args.install:
        if not ensure_package_manager(plat, dry_run=args.dry_run):
            return 1
        managers_fresh = detect_pkg_managers()  # refresh after ensure

        todo = sorted(
            [r for r in rows if r["applicable"] and not r["installed"]],
            key=lambda r: (not bool(r["app"].get("bootstrap")), r["name"].lower()),
        )
        if not todo:
            ok("All applicable apps are already installed!")
            return 0

        info(f"Selection: {profile_label(args)}")
        info(f"Apps to install: {bold(str(len(todo)))}")
        for r in todo:
            info(f"  • {r['name']}")
        print()

        done, errs = 0, 0
        for r in todo:
            app = r["app"]
            rec: dict = {"name": app["name"], "phase": "install"}
            info(f"Installing {bold(app['name'])} …")
            success, msg = install_app(app, plat["os"], managers_fresh, dry_run=args.dry_run)
            rec["install"] = {"status": "ok" if success else "fail", "detail": msg}
            if success:
                ok(f"{app['name']}: {msg}")
                done += 1
            else:
                fail(f"{app['name']}: {msg}")
                errs += 1

            # Run post-install steps
            post_cmds = get_post_install_cmds(app, plat["os"])
            if post_cmds and success:
                post_ok, post_msgs = run_post_install(app, plat["os"], dry_run=args.dry_run)
                for pm in post_msgs:
                    tag = green("✓") if pm.startswith("OK:") or pm.startswith("dry-run:") else red("✗")
                    info(f"    {tag} {pm}")
                if not post_ok:
                    warn(f"  Some post-install steps failed for {app['name']}")
                rec["post_install"] = {
                    "status": "ok" if post_ok else "fail",
                    "steps": post_msgs,
                }

            # Run configure steps (unless skipped)
            if success and not args.skip_configure and get_configure_steps(app, plat["os"]):
                cfg_ok, cfg_results = run_configure(
                    app, plat["os"], creds,
                    non_interactive_only=args.non_interactive,
                    dry_run=args.dry_run,
                )
                if cfg_ok:
                    ok(f"{app['name']}: configure complete")
                else:
                    warn(f"  Some configure steps failed/skipped for {app['name']}")
                rec["configure"] = {
                    "status": "ok" if cfg_ok else "fail",
                    "steps": cfg_results,
                }

            # Show platform-specific note if present
            nk = f"install_{plat['os']}_note"
            if nk in app:
                info(f"  ℹ  {app[nk]}")
            summary_records.append(rec)
            print()

        already = sum(1 for r in rows if r["installed"] is True)
        info("━" * 55)
        info(f"Done.  Installed: {done}  Failed: {errs}  Already present: {already}")
        info("━" * 55)
        _print_run_summary(summary_records)
        _write_run_summary_json(summary_records, plat)
        return 1 if errs else 0

    # ── verify (simulators / emulators / post-install state) ─────────
    if args.verify:
        targets = [r for r in rows
                   if r["applicable"] and r["installed"]
                   and get_verify_checks(r["app"], plat["os"])]
        if not targets:
            ok("No verification checks defined for installed apps.")
            return 0

        info(f"Apps with verification checks: {bold(str(len(targets)))}")
        for r in targets:
            info(f"  • {r['name']}  ({len(get_verify_checks(r['app'], plat['os']))} check(s))")
        print()

        all_good = True
        for r in targets:
            app = r["app"]
            info(f"Verifying {bold(app['name'])} …")
            v_ok, results = run_verify(app, plat["os"])
            for res in results:
                tag = green("✓") if res["ok"] else red("✗")
                info(f"  {tag} {bold(res['label'])}:")
                for line in res["output"].split("\n"):
                    info(f"      {line}")
            if v_ok:
                ok(f"{app['name']}: All checks passed")
            else:
                warn(f"{app['name']}: Some checks failed")
                all_good = False
            print()

        info("━" * 55)
        if all_good:
            ok("All verification checks passed.")
        else:
            warn("Some verification checks failed — review output above.")
        info("━" * 55)
        return 0 if all_good else 1

    # ── setup (post-install for already-installed apps) ───────────────
    if args.setup:
        targets = [r for r in rows
                   if r["applicable"] and r["installed"]
                   and get_post_install_cmds(r["app"], plat["os"])]
        if not targets:
            ok("No post-install steps to run for installed apps.")
            return 0

        info(f"Apps with post-install steps: {bold(str(len(targets)))}")
        for r in targets:
            info(f"  • {r['name']}  ({len(get_post_install_cmds(r['app'], plat['os']))} step(s))")
        print()

        done, errs = 0, 0
        for r in targets:
            app = r["app"]
            rec: dict = {"name": app["name"], "phase": "setup"}
            info(f"Setting up {bold(app['name'])} …")
            post_ok, post_msgs = run_post_install(app, plat["os"], dry_run=args.dry_run)
            for pm in post_msgs:
                tag = green("✓") if pm.startswith("OK:") or pm.startswith("dry-run:") else red("✗")
                info(f"    {tag} {pm}")
            if post_ok:
                ok(f"{app['name']}: Post-install complete")
                done += 1
            else:
                fail(f"{app['name']}: Some post-install steps failed")
                errs += 1
            rec["post_install"] = {
                "status": "ok" if post_ok else "fail",
                "steps": post_msgs,
            }
            summary_records.append(rec)

            nk = f"install_{plat['os']}_note"
            if nk in app:
                info(f"  ℹ  {app[nk]}")
            print()

        info("━" * 55)
        info(f"Setup done.  Success: {done}  Failed: {errs}")
        info("━" * 55)
        _print_run_summary(summary_records)
        _write_run_summary_json(summary_records, plat)
        return 1 if errs else 0

    # ── configure (configure steps for already-installed apps) ────────
    if args.configure:
        targets = [r for r in rows
                   if r["applicable"] and r["installed"]
                   and get_configure_steps(r["app"], plat["os"])]
        if not targets:
            ok("No configure steps to run for installed apps.")
            return 0

        info(f"Apps with configure steps: {bold(str(len(targets)))}")
        for r in targets:
            info(f"  • {r['name']}  ({len(get_configure_steps(r['app'], plat['os']))} step(s))")
        print()

        done, errs = 0, 0
        for r in targets:
            app = r["app"]
            rec: dict = {"name": app["name"], "phase": "configure"}
            info(f"Configuring {bold(app['name'])} …")
            cfg_ok, cfg_results = run_configure(
                app, plat["os"], creds,
                non_interactive_only=args.non_interactive,
                dry_run=args.dry_run,
            )
            rec["configure"] = {
                "status": "ok" if cfg_ok else "fail",
                "steps": cfg_results,
            }
            if cfg_ok:
                ok(f"{app['name']}: Configure complete")
                done += 1
            else:
                fail(f"{app['name']}: Some configure steps failed/skipped")
                errs += 1
            summary_records.append(rec)
            print()

        info("━" * 55)
        info(f"Configure done.  Success: {done}  Failed: {errs}")
        info("━" * 55)
        _print_run_summary(summary_records)
        _write_run_summary_json(summary_records, plat)
        return 1 if errs else 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
