#!/usr/bin/env python3
"""Read-only macOS residual/policy audit for the disk-cleanup skill.

This is a *detect only* companion to ``storage_cleanup.py``. It never deletes
anything. It surfaces the kinds of leftovers the cleanup helper cannot safely
bulk-remove by itself:

- LaunchAgent / LaunchDaemon jobs whose target binary no longer exists (dead
  references left behind by uninstalled apps);
- launchd jobs exiting with abnormal status codes (the "spawn scheduled"
  thrash pattern from a vanished target);
- empty-shell plists (no ``Label``/empty ``{}``) that launchd can't load;
- ``PrivilegedHelperTools`` <-> ``LaunchDaemons`` pairing mismatches;
- orphan keys in the launchd ``disabled.*.plist`` override records;
- per-app residual folders under ``~/Library`` (Caches, Containers,
  HTTPStorages, WebKit, Saved Application State, Group Containers) whose
  bundle-id name belongs to an app that is no longer installed;
- developer tool caches: discovered structurally (not a frozen tool list) and
  analysed for **multi-version** directories, flagging which versions are
  stale (all-but-latest per group) as reclamation candidates (report only).

The orphan-folder findings mirror what ``storage_cleanup.py`` can later remove
with the app-aware ``orphan-folders`` / ``orphan-caches`` scans, so this script
is a safe pre-flight "what would be reclaimed / what needs manual review".

Run with ``--json`` to get a machine-readable summary.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

from app_probe import _installed_app_index, is_app_installed, looks_like_bundle_id
from cleanup_common import dir_size_no_follow, human_size

# --- paths -----------------------------------------------------------------

HOME = os.path.expanduser("~")

LAUNCH_DIRS = [
    os.path.join(HOME, "Library", "LaunchAgents"),
    "/Library/LaunchAgents",
    "/Library/LaunchDaemons",
    os.path.join(HOME, "Library", "LaunchDaemons"),
]

# System launch dirs — only used by the disabled-record orphan check so that
# Apple's own services (e.g. com.apple.ftpd) are not falsely flagged as
# orphans. Excluded from dead-target/empty-shell checks to avoid noise about
# macOS-internal daemons the user should never touch.
LAUNCH_DIRS_SYSTEM = [
    "/System/Library/LaunchDaemons",
    "/System/Library/LaunchAgents",
]

# Per-app residual folders under ~/Library whose child subfolders are named by
# bundle id. A child whose app is uninstalled is a safe orphan reclaim.
ORPHAN_DIRS = [
    os.path.join(HOME, "Library", "Caches"),
    os.path.join(HOME, "Library", "Containers"),
    os.path.join(HOME, "Library", "HTTPStorages"),
    os.path.join(HOME, "Library", "WebKit"),
    os.path.join(HOME, "Library", "Saved Application State"),
    os.path.join(HOME, "Library", "Group Containers"),
]

# Developer tool caches are *not* enumerated as a frozen per-tool list in code.
# Instead the audit discovers them structurally (see discover_dev_caches) and
# then analyses versioned subdirectories generically. The authoritative,
# human-readable per-tool knowledge (npm/pnpm/yarn/pip/Gradle/Maven/Cargo/Go/
# Rustup/Xcode/Playwright/Homebrew, plus the safe per-tool commands and the
# multi-version strategy) lives in references/macos-cleanup.md, not here.

# Seed dirs: well-known tool "home cache" directories. These guarantee we catch
# the heavy hitters even when the broad scan below misses them. This is a small
# *seed*, not the full catalogue — discovery does the rest.
DEV_CACHE_SEEDS = (
    ".gradle", ".cargo", ".rustup", ".m2", ".npm", ".cache",
    ".gem", ".composer", ".nuget", ".android", ".bundle", ".stack",
    ".cabal", ".sbt", ".mamba", ".conda", ".julia", ".dotnet", ".helm",
    ".kube", ".terraform", ".vagrant.d",
)

# Parent directories scanned to discover *additional* caches that are not in
# the seed list (and not app bundle-id caches, which are reported elsewhere).
# ~/Library/Developer (Xcode/CoreSimulator) is intentionally excluded: its
# trees are huge, yield no useful version groups, and are handled by the
# helper's `developer` profile + the reference doc.
DEV_CACHE_PARENTS = (
    "~/Library/Caches",
    "~/.cache",
    "~/.local/share",
    "~/go/pkg",
    "~/.config",
)

# A cache dir larger than this is reported by size only (version analysis is
# skipped) to keep the audit fast and bounded.
DEV_CACHE_MAX_VERSION_SCAN_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

# Monolithic trees that are slow to walk and never yield useful version groups.
DEV_CACHE_SKIP_ANALYSIS_SUBSTR = ("Xcode", "CoreSimulator")

# The expensive per-root version walk is run only for seed dirs and for
# discovered caches whose name looks like a dependency/tool cache (not app
# caches like Edge/Firefox). Discovery itself stays fully generic — every
# discovered cache is still sized and listed via `du`.
DEV_CACHE_ANALYZE_NAMES = (
    "homebrew", "yarn", "cocoapods", "pip", "playwright", "go-build",
    "gradle", "cargo", "rustup", "maven", "m2", "npm", "pnpm", "gem",
    "conda", "mamba", "julia", "dotnet", "nuget", "composer", "helm",
    "kube", "terraform", "kylin", "opencode", "codebuddy", "claude",
    "codex", "android", "sbt", "cabal", "stack", "vagrant", "mod",
)

# Stop walking a cache root deeper than this to bound runtime.
DEV_CACHE_MAX_DEPTH = 4


@dataclass
class AuditReport:
    installed_apps: int = 0
    dead_targets: list[str] = field(default_factory=list)
    abnormal_jobs: list[str] = field(default_factory=list)
    empty_plists: list[str] = field(default_factory=list)
    helper_daemon_mismatch: list[str] = field(default_factory=list)
    disabled_orphans: list[str] = field(default_factory=list)
    orphan_folders: list[dict] = field(default_factory=list)
    dev_caches: list[dict] = field(default_factory=list)


# --- helpers ---------------------------------------------------------------

def _run(args: list[str]) -> str | None:
    """Run a command, return stdout or None on any failure."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _plist_value(path: str, key: str) -> str | None:
    """Read a plist value via PlistBuddy. Returns None if missing/unreadable."""
    out = _run(["/usr/libexec/PlistBuddy", "-c", f"Print :{key}", path])
    if out is None:
        return None
    return out.strip()


def _expand(path: str) -> str:
    return os.path.expanduser(os.path.expandvars(path))


# Real paths of the seed tool dirs, for cheap membership tests in the audit.
_SEED_REAL_PATHS = {
    os.path.realpath(_expand(os.path.join(HOME, s))) for s in DEV_CACHE_SEEDS
}


def _du_size_bytes(path: str) -> int:
    """Fast native size of ``path`` via ``du -sk`` (avoids slow Python walks)."""
    out = _run(["du", "-sk", path])
    if not out:
        return 0
    m = re.match(r"(\d+)", out.splitlines()[0])
    if not m:
        return 0
    return int(m.group(1)) * 1024


# --- individual checks -----------------------------------------------------

def count_installed_apps() -> int:
    # Reuse the same index the orphan scan relies on (it uses glob, so it
    # follows symlinked .app bundles that os.walk would skip).
    ids, _names = _installed_app_index()
    return len(ids)


def check_dead_targets() -> list[str]:
    """LaunchAgents/Daemons whose Program/ProgramArguments no longer exist."""
    findings: list[str] = []
    plist_globs = []
    for d in LAUNCH_DIRS:
        if os.path.isdir(d):
            plist_globs.append(d)
    import glob
    for d in plist_globs:
        for plist in sorted(glob.glob(os.path.join(d, "*.plist"))):
            binpath = _plist_value(plist, "ProgramArguments:0")
            if not binpath:
                binpath = _plist_value(plist, "Program")
            if not binpath:
                continue
            if not os.path.exists(binpath):
                findings.append(
                    f"{os.path.basename(plist)} -> {binpath} (missing)"
                )
    return findings


def check_abnormal_jobs() -> list[str]:
    """launchctl jobs with a non-zero exit status (thrashing / dead targets)."""
    out = _run(["launchctl", "list"])
    if out is None:
        return []
    findings: list[str] = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        status, label = parts[1], parts[2]
        if re.fullmatch(r"-?\d+", status) and status != "0":
            findings.append(f"exit {status}: {label}")
    return findings


def check_empty_plists() -> list[str]:
    """Plists without a Label (empty shells launchd cannot load)."""
    findings: list[str] = []
    import glob
    for d in LAUNCH_DIRS:
        if not os.path.isdir(d):
            continue
        for plist in sorted(glob.glob(os.path.join(d, "*.plist"))):
            if _plist_value(plist, "Label") is None:
                findings.append(os.path.basename(plist))
    return findings


def check_helper_daemon_pairing() -> list[str]:
    """PrivilegedHelperTools <-> LaunchDaemons should come in pairs."""
    findings: list[str] = []
    helper_root = "/Library/PrivilegedHelperTools"
    daemon_root = "/Library/LaunchDaemons"
    if os.path.isdir(helper_root):
        for entry in sorted(os.listdir(helper_root)):
            name = entry[:-len(".bundle")] if entry.endswith(".bundle") else entry
            if not os.path.isfile(os.path.join(daemon_root, f"{name}.plist")):
                findings.append(f"helper without daemon: {name}")
    if os.path.isdir(daemon_root):
        for plist in sorted(os.listdir(daemon_root)):
            if not plist.endswith(".plist"):
                continue
            name = plist[:-len(".plist")]
            helper = os.path.join(helper_root, name)
            helper_bundle = os.path.join(helper_root, f"{name}.bundle")
            if not (os.path.exists(helper) or os.path.exists(helper_bundle)):
                findings.append(f"daemon without helper: {name}")
    return findings


def check_disabled_orphans() -> list[str]:
    """Orphan keys in launchd disabled override records (no plist defines it)."""
    findings: list[str] = []
    uid = os.getuid()
    for f in (
        "/var/db/com.apple.xpc.launchd/disabled.plist",
        f"/var/db/com.apple.xpc.launchd/disabled.{uid}.plist",
    ):
        if not os.path.isfile(f):
            continue
        out = _run(["plutil", "-p", f])
        if not out:
            continue
        keys = re.findall(r'"([^"]+)"\s*=>', out)
        search_dirs = LAUNCH_DIRS + LAUNCH_DIRS_SYSTEM
        for key in keys:
            found = False
            import glob
            for d in search_dirs:
                if not os.path.isdir(d):
                    continue
                for plist in glob.glob(os.path.join(d, "*.plist")):
                    try:
                        with open(plist, "r", errors="ignore") as handle:
                            if key in handle.read():
                                found = True
                                break
                    except OSError:
                        continue
                if found:
                    break
            if not found:
                findings.append(key)
    return findings


def check_orphan_folders() -> list[dict]:
    """Per-app residual folders under ~/Library whose app is uninstalled."""
    findings: list[dict] = []
    for base in ORPHAN_DIRS:
        base = _expand(base)
        if not os.path.isdir(base):
            continue
        try:
            children = sorted(os.listdir(base))
        except OSError:
            continue
        for name in children:
            child = os.path.join(base, name)
            if not os.path.isdir(child) or name.startswith("."):
                continue
            # strip known suffixes so e.g. "com.apple.Safari.savedState" matches
            token = name
            for suffix in (".savedState", ".binarycookies"):
                if token.endswith(suffix):
                    token = token[: -len(suffix)]
            if not looks_like_bundle_id(token):
                continue
            if is_app_installed(token):
                continue
            size = dir_size_no_follow(child)
            findings.append(
                {
                    "path": os.path.relpath(child, HOME),
                    "bytes": size,
                    "size": human_size(size),
                }
            )
    return findings


def check_dev_cache_sizes() -> list[dict]:
    """Discover developer tool caches and analyse multi-version directories.

    Discovery is structural, not a hardcoded tool list: a small seed of known
    tool home dirs plus a broad scan of common cache parents. App bundle-id
    caches are skipped (they are reported by the orphan-folder check instead).
    For each discovered cache, versioned subdirectories (e.g.
    ``~/.gradle/caches/8.10.2``, ``~/.cargo/registry/src/<h>/<crate>-0.57``,
    ``~/.rustup/toolchains/1.97.1-x86_64``) are grouped and every version except
    the latest is flagged as a stale reclamation candidate.
    """
    caches = []
    seen: set[str] = set()
    for path in discover_dev_caches():
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        if not os.path.isdir(path):
            continue
        # Size via native `du` (fast even for multi-GB trees); Python walks are
        # reserved for the bounded version analysis below.
        total = _du_size_bytes(path)
        if total <= 0:
            continue
        groups: list[dict] = []
        stale_bytes = 0
        base_lower = os.path.basename(path).lower()
        analyzable = (
            total <= DEV_CACHE_MAX_VERSION_SCAN_BYTES
            and real not in _SEED_REAL_PATHS
            and not any(s in path for s in DEV_CACHE_SKIP_ANALYSIS_SUBSTR)
            and any(tok in base_lower for tok in DEV_CACHE_ANALYZE_NAMES)
        ) or (real in _SEED_REAL_PATHS and total <= DEV_CACHE_MAX_VERSION_SCAN_BYTES)
        if analyzable:
            groups, stale_bytes = analyze_versions(path)
        caches.append(
            {
                "path": os.path.relpath(path, HOME),
                "bytes": total,
                "size": human_size(total),
                "version_groups": groups[:15],
                "group_count": len(groups),
                "stale_bytes": stale_bytes,
                "stale_size": human_size(stale_bytes),
            }
        )
    caches.sort(key=lambda x: x["bytes"], reverse=True)
    return caches[:25]


def discover_dev_caches() -> list[str]:
    """Return candidate developer cache directories to inspect.

    Combines a seed of well-known tool home dirs with a broad scan of common
    cache parents, skipping app bundle-id caches (reported elsewhere).
    """
    found: list[str] = []
    # 1. Seed tool home dirs.
    for seed in DEV_CACHE_SEEDS:
        p = _expand(os.path.join(HOME, seed))
        if os.path.isdir(p) and not looks_like_bundle_id(os.path.basename(p)):
            found.append(p)
    # 2. Broad scan of cache parents for additional, non-app caches.
    for parent in DEV_CACHE_PARENTS:
        pdir = _expand(parent)
        if not os.path.isdir(pdir):
            continue
        try:
            entries = sorted(os.listdir(pdir))
        except OSError:
            continue
        for name in entries:
            if looks_like_bundle_id(name):
                continue  # app cache — handled by orphan check
            child = os.path.join(pdir, name)
            if os.path.isdir(child) and not os.path.islink(child):
                found.append(child)
    return found


_SEMVER_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z._\-]+)?)")


def _split_version(name: str) -> tuple[str | None, str | None]:
    """Split ``<base>-<version>`` or bare ``<version>``.

    Returns ``(base, version)`` where ``base`` is ``None`` for a bare version
    directory (e.g. ``8.10.2``). Returns ``(name, None)`` if no version found.
    """
    matches = list(_SEMVER_RE.finditer(name))
    if not matches:
        return name, None
    version = matches[-1].group(1)
    base = name[: matches[-1].start()].rstrip("-._")
    if not base:
        return None, version
    return base, version


def _semver_key(version: str):
    """Return a comparable key ``((major,minor,patch), release_rank, prerelease)``.

    Releases rank above prereleases (``1.0.0`` > ``1.0.0-beta``); among
    prereleases, lexical order of the suffix applies.
    """
    nums = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", version)
    if not nums:
        return ((0, 0, 0), 0, version)
    triple = tuple(int(nums.group(i) or 0) for i in (1, 2, 3))
    remainder = version[nums.end():]
    if remainder.startswith(("-", "+")):
        return (triple, 0, remainder[1:])  # prerelease ranks below release
    return (triple, 1, "")


def _pick_latest(
    versions: list[tuple[str, str, float]]
) -> tuple[str, str, float]:
    """Pick the latest version tuple. Semver order, then mtime as tiebreak."""

    def key(v: tuple[str, str, float]):
        sk = _semver_key(v[0])
        return (sk[0], sk[1], sk[2], v[2])

    try:
        return max(versions, key=key)
    except (ValueError, TypeError):
        return max(versions, key=lambda v: v[2])


def analyze_versions(root: str) -> tuple[list[dict], int]:
    """Group versioned subdirectories under ``root`` and flag stale ones.

    Traverses cheaply (no per-file byte counting) and sizes only the stale
    version directories via native ``du`` (capped to bound runtime). Returns
    ``(groups, total_stale_bytes)``. A "group" is a set of sibling directories
    sharing the same base name but differing in version; the non-latest
    versions are stale reclamation candidates.
    """
    raw: dict[tuple[str, str | None], list[tuple[str, str, float]]] = {}
    for dirpath, dirnames, _filenames in os.walk(root, followlinks=False):
        depth = dirpath[len(root):].count(os.sep)
        if depth > DEV_CACHE_MAX_DEPTH:
            dirnames[:] = []
            continue
        name = os.path.basename(dirpath)
        base, version = _split_version(name)
        if version is None:
            continue
        try:
            mtime = os.lstat(dirpath).st_mtime
        except OSError:
            mtime = 0.0
        raw.setdefault((os.path.dirname(dirpath), base), []).append(
            (version, dirpath, mtime)
        )

    groups: list[dict] = []
    total_stale = 0
    measured = 0
    max_du_calls = 400  # bound runtime on caches with enormous version counts
    for (parent, base), vers in raw.items():
        if len(vers) < 2:
            continue
        latest = _pick_latest(vers)
        stale = [v for v in vers if v[1] != latest[1]]
        stale_bytes = 0
        for v in stale:
            if measured < max_du_calls:
                stale_bytes += _du_size_bytes(v[1])
                measured += 1
        total_stale += stale_bytes
        groups.append(
            {
                "parent": os.path.relpath(parent, HOME),
                "base": base or "(version dirs)",
                "versions": sorted(v[0] for v in vers),
                "count": len(vers),
                "stale_count": len(stale),
                "stale_bytes": stale_bytes,
                "stale_size": human_size(stale_bytes),
            }
        )
    groups.sort(key=lambda g: g["stale_bytes"], reverse=True)
    return groups, total_stale


# --- driver ----------------------------------------------------------------

def _safe(fn, default):
    """Run a check, returning ``default`` if it raises (audit must not crash)."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 - a single failing check must not blank the report
        return default


def run_audit() -> AuditReport:
    report = AuditReport()
    report.installed_apps = _safe(count_installed_apps, 0)
    report.dead_targets = _safe(check_dead_targets, [])
    report.abnormal_jobs = _safe(check_abnormal_jobs, [])
    report.empty_plists = _safe(check_empty_plists, [])
    report.helper_daemon_mismatch = _safe(check_helper_daemon_pairing, [])
    report.disabled_orphans = _safe(check_disabled_orphans, [])
    report.orphan_folders = _safe(check_orphan_folders, [])
    report.dev_caches = _safe(check_dev_cache_sizes, [])
    return report


def _print(report: AuditReport) -> None:
    def section(title: str) -> None:
        print(f"\033[0;32m==>\033[0m {title}")

    section(f"Installed apps: {report.installed_apps}")

    section("LaunchAgent/Daemon targets that no longer exist")
    if report.dead_targets:
        for f in report.dead_targets:
            print(f"  \033[1;33m? {f}\033[0m")
    else:
        print("  (none)")

    section("launchd jobs with abnormal exit status")
    if report.abnormal_jobs:
        for f in report.abnormal_jobs:
            print(f"  \033[1;33m? {f}\033[0m")
    else:
        print("  (none)")

    section("Empty-shell plists (no Label)")
    if report.empty_plists:
        for f in report.empty_plists:
            print(f"  \033[1;33m? {f}\033[0m")
    else:
        print("  (none)")

    section("PrivilegedHelperTools <-> LaunchDaemons pairing")
    if report.helper_daemon_mismatch:
        for f in report.helper_daemon_mismatch:
            print(f"  \033[1;33m? {f}\033[0m")
    else:
        print("  (none)")

    section("Orphan keys in launchd disabled records")
    if report.disabled_orphans:
        for f in report.disabled_orphans:
            print(f"  \033[1;33m? {f}\033[0m")
    else:
        print("  (none)")

    section("Orphan app residual folders (app uninstalled)")
    if report.orphan_folders:
        total = 0
        for item in report.orphan_folders:
            total += item["bytes"]
            print(f"  \033[1;33m? {item['path']}  {item['size']}\033[0m")
        print(f"  total reclaimable: {human_size(total)}")
    else:
        print("  (none)")

    section("Large caches (discovered: dev tools + ~/Library/Caches)")
    if report.dev_caches:
        for item in report.dev_caches:
            tail = ""
            if item["group_count"]:
                tail = (
                    f"  [{item['group_count']} version group(s), "
                    f"~{item['stale_size']} stale (all-but-latest)]"
                )
            print(f"  {item['path']:<46} {item['size']:<8}{tail}")
        print(
            "  App caches under ~/Library/Caches regenerate; dev caches can be"
        )
        print(
            "  wiped and rebuilt. See references/macos-cleanup.md (Developer"
        )
        print(
            "  tool caches) for per-tool safe commands and the multi-version"
        )
        print("  strategy (keep latest per group; cross-check lockfiles).")
    else:
        print("  (none)")

    print(
        "\nAudit complete. Items marked '?' need human judgement before "
        "removal. Run storage_cleanup.py --apply for the safe orphan folders."
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    as_json = "--json" in argv
    report = run_audit()
    if as_json:
        print(json.dumps(report.__dict__, indent=2, sort_keys=True))
    else:
        _print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
