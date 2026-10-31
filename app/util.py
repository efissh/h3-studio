"""Tiny helpers shared by the app."""
from __future__ import annotations

import os
from pathlib import Path


def sys_bin(name: str) -> str:
    """Absolute path of a macOS system tool (so a poisoned PATH can't substitute it); falls back to the bare name elsewhere."""
    for d in ("/usr/bin", "/usr/sbin", "/bin", "/sbin"):
        p = Path(d) / name
        if os.access(p, os.X_OK):
            return str(p)
    return name
