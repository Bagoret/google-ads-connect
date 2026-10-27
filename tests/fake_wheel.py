"""Builds a SYNTHETIC stand-in wheel for google-ads-mcp so setup tests can install it offline.

The wheel is named google-ads-mcp 0.0.5 and provides a `google-ads-mcp` console script that runs
tests/fake_mcp_server.py (path taken from $FAKE_SERVER at run time). It never talks to Google.
"""
from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path

NAME, VERSION = "google_ads_mcp", "0.0.5"
MODULE = '''import os
import runpy


def run():
    runpy.run_path(os.environ["FAKE_SERVER"], run_name="__main__")
'''


def _record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{name},sha256={digest},{len(data)}"


def build(directory: Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    info = f"{NAME}-{VERSION}.dist-info"
    files = {
        "fake_ads_mcp.py": MODULE.encode(),
        f"{info}/METADATA": f"Metadata-Version: 2.1\nName: google-ads-mcp\nVersion: {VERSION}\n".encode(),
        f"{info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: fake_wheel\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{info}/entry_points.txt": b"[console_scripts]\ngoogle-ads-mcp = fake_ads_mcp:run\n",
    }
    record = [_record_line(n, d) for n, d in files.items()] + [f"{info}/RECORD,,"]
    path = directory / f"{NAME}-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as zf:
        for n, d in files.items():
            zf.writestr(n, d)
        zf.writestr(f"{info}/RECORD", "\n".join(record) + "\n")
    return path
