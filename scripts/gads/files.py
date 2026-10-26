"""Writing small private files (profiles, MCP config) atomically with owner-only permissions."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_private_json(path: Path, data) -> None:
    """Replace path with data as JSON, mode 600, via a temp file so a crash never leaves it half-written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
