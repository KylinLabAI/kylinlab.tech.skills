#!/usr/bin/env python3
"""macOS app-presence probing for the disk-cleanup helper.

Used by the orphan-cache scan so the helper only removes cache / container
folders whose owning application is no longer installed. A cache folder whose
app is still installed is never bulk-removed; it only gets the normal
age-based cleanup.

Detection strategy (safe, no destructive actions here):
1. `com.apple.*` identifiers are always treated as present (system components).
2. Prefer Spotlight's `mdfind` for an exact bundle-id match (fast, indexed).
3. Fall back to a shallow scan of the common Applications folders, reading each
   app's `Contents/Info.plist` for `CFBundleIdentifier` / `CFBundleName`.

The scan result is cached for the lifetime of the process so repeated probes
stay cheap.
"""

from __future__ import annotations

import glob
import os
import plistlib
import subprocess
from functools import lru_cache

# Common locations where user- and system-installed apps live. We only look one
# level deep so we don't try to parse the hundreds of nested helper apps inside
# bundles like Xcode (whose ids are covered by the com.apple.* rule anyway).
_APP_DIRS = (
    "/Applications",
    "/System/Applications",
    "/Library/Applications",
    os.path.expanduser("~/Applications"),
)

_CACHE: dict[str, tuple[set[str], set[str]]] = {}


def looks_like_bundle_id(name: str) -> bool:
    """A cache/container folder named like a reverse-DNS bundle id.

    e.g. ``com.google.Chrome`` -> True, but ``Firefox`` or ``Code Cache`` -> False.
    Names we cannot classify are left untouched to avoid false deletions.
    """
    if not name or name.startswith("."):
        return False
    return "." in name


@lru_cache(maxsize=1)
def _installed_app_index() -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    names: set[str] = set()
    for base in _APP_DIRS:
        if not os.path.isdir(base):
            continue
        for pattern in (os.path.join(base, "*.app"), os.path.join(base, "*", "*.app")):
            for app in glob.glob(pattern):
                info = os.path.join(app, "Contents", "Info.plist")
                try:
                    with open(info, "rb") as handle:
                        plist = plistlib.load(handle)
                except (OSError, plistlib.InvalidFileException):
                    continue
                bundle_id = plist.get("CFBundleIdentifier")
                if bundle_id:
                    ids.add(bundle_id)
                app_name = plist.get("CFBundleName") or os.path.basename(app)[:-4]
                if app_name:
                    names.add(app_name.lower())
    return ids, names


def _spotlight_match(bundle_id: str) -> bool:
    try:
        result = subprocess.run(
            ["mdfind", f"kMDItemCFBundleIdentifier == '{bundle_id}'"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.rstrip().endswith(".app") for line in result.stdout.splitlines())


def is_app_installed(token: str) -> bool:
    """Return True if an app identified by ``token`` (bundle id or name) is installed.

    Always True for ``com.apple.*`` system components so their caches are never
    treated as orphans.

    Detection order is chosen to stay cheap when called thousands of times:
    1. ``com.apple.*`` -> present.
    2. membership in the one-time scanned app index (no subprocess).
    3. only for tokens not found in the index, a single ``mdfind`` Spotlight
       lookup as a last-resort safety net for apps in non-standard locations.
    """
    if not token:
        return False
    if token.startswith("com.apple."):
        return True

    ids, names = _installed_app_index()
    if token in ids:
        return True
    if token.lower() in names:
        return True

    # Rare path: index miss -> confirm via Spotlight before treating as orphan.
    return _spotlight_match(token)
