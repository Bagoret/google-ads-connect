"""Restores platform.mac_ver() when Python cannot read the macOS version (copied into the MCP server venv).

Why: Homebrew's Python bottles built for macOS 26.3+ link pyexpat against the system libexpat, which on
macOS 26.0-26.2 lacks a symbol they need, so `import pyexpat` fails. platform.mac_ver() reads
SystemVersion.plist with plistlib (an XML parser on top of pyexpat), swallows the ImportError and returns ''.
pip's vendored truststore and packaging, and httpx2 at run time, then crash on int('').

scripts/setup_config.py copies this file into the server's own venv as `google_ads_os_macver.py`, with a .pth
file that imports it at interpreter start. It only patches the venv's processes, only on macOS, only when
mac_ver() is empty, and never raises. Standard library only; must stay self-contained.
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
import sys

PLIST = "/System/Library/CoreServices/SystemVersion.plist"
SW_VERS = "/usr/bin/sw_vers"
_VERSION = re.compile(r"<key>ProductVersion</key>\s*<string>\s*(\d+(?:\.\d+){0,2})\s*</string>")


def product_version(plist_path: str = PLIST, sw_vers: str = SW_VERS) -> str:
    """The macOS version ('26.2'), read without an XML parser; '' if it cannot be found."""
    try:
        with open(plist_path, "rb") as fh:
            match = _VERSION.search(fh.read().decode("utf-8", "replace"))
        if match:
            return match.group(1)
    except OSError:
        pass
    try:
        out = subprocess.run([sw_vers, "-productVersion"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return out if re.fullmatch(r"\d+(?:\.\d+){0,2}", out) else ""


def install(platform_module=platform, sys_platform: str = sys.platform, plist_path: str = PLIST,
            sw_vers: str = SW_VERS) -> bool:
    """Replace platform_module.mac_ver if it returns no version on macOS. Returns True if it patched."""
    if sys_platform != "darwin":
        return False
    try:
        if platform_module.mac_ver()[0]:
            return False
    except Exception:
        pass
    release = product_version(plist_path, sw_vers)
    if not release:
        return False

    def mac_ver(release_: str = "", versioninfo=("", "", ""), machine: str = ""):
        return release, versioninfo, machine or os.uname().machine

    platform_module.mac_ver = mac_ver
    return True


try:
    install()
except Exception:  # a .pth import must never stop the interpreter from starting
    pass
