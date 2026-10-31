"""Read-only environment diagnostics.  ``python -m app.doctor [--json]``

Never changes anything, never prints secrets (the H3cApp token is only checked for existence), and only talks to the
local H3cApp API on loopback.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .models import SUPPORT_DIR, h3capp_app_path, h3capp_version
from .util import sys_bin

ROOT = Path(__file__).resolve().parent.parent
H3_URL = os.environ.get("H3C_API_URL", "http://127.0.0.1:8420")
TOKEN_FILE = Path(os.environ.get("H3C_TOKEN_FILE", SUPPORT_DIR / "api-token"))


def _sh(*cmd: str, timeout: float = 5.0) -> str:
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def chip_info(brand: str, mem_bytes: int) -> dict:
    """Pure helper: what can be said about this Mac from its chip string and RAM."""
    m = re.search(r"Apple (M(\d+)\s*(Pro|Max|Ultra)?)", brand or "")
    gen = int(m.group(2)) if m else None
    return {"brand": brand or "unknown", "family": m.group(1).strip() if m else None, "generation": gen,
            "apple_silicon": bool(m), "memory_gb": round(mem_bytes / 2**30) if mem_bytes else None,
            "int8_cache_capable": bool(gen and gen >= 5)}


def advice(info: dict) -> list:
    """Pure helper: plain-language hints, deliberately conservative (H3cApp's own docs are the authority on RAM needs)."""
    out = []
    if not info["apple_silicon"]:
        out.append(("fail", "H3cApp needs an Apple Silicon Mac (Intel is not supported)."))
        return out
    if info["int8_cache_capable"]:
        out.append(("ok", "M5-class GPU: the Fast INT8 cache can be built in H3cApp (Advanced Settings) for each model."))
    else:
        out.append(("info", "No M5-class GPU: the INT8 cache is not available; models run in Resident mode (or SSD streaming if enabled)."))
    mem = info["memory_gb"] or 0
    if mem and mem < 24:
        out.append(("warn", f"{mem} GB unified memory is below the 24 GB H3cApp recommends; expect failures or heavy swapping."))
    elif mem and mem < 64:
        out.append(("info", f"{mem} GB unified memory: large BF16 models may need the INT8 cache or SSD streaming; see H3cApp's docs."))
    return out


def _api(path: str) -> Optional[object]:
    import httpx
    try:
        tok = TOKEN_FILE.read_text().strip()
        r = httpx.get(H3_URL + path, headers={"Authorization": f"Bearer {tok}"}, timeout=3)
        return r.json() if r.status_code == 200 else f"HTTP {r.status_code}"
    except Exception as e:
        return f"error: {type(e).__name__}"


def run_checks() -> list:
    res = []
    add = lambda name, status, detail="": res.append({"name": name, "status": status, "detail": detail})
    add("python", "ok" if sys.version_info >= (3, 10) else "fail", platform.python_version() + ("" if sys.version_info >= (3, 10) else ": 3.10+ is required (security fixes in dependencies); brew install python@3.12, then ./install.sh"))
    if platform.system() != "Darwin":
        add("platform", "warn", f"{platform.system()}: H3 Studio targets macOS; only tests and the demo run elsewhere.")
    else:
        brand = _sh(sys_bin("sysctl"), "-n", "machdep.cpu.brand_string")
        mem = int(_sh(sys_bin("sysctl"), "-n", "hw.memsize") or 0)
        info = chip_info(brand, mem)
        add("chip", "ok" if info["apple_silicon"] else "fail", f"{info['brand']}, {info['memory_gb']} GB unified memory, macOS {platform.mac_ver()[0]}")
        for st, text in advice(info):
            add("hardware", st, text)
    for mod in ("fastapi", "uvicorn", "httpx", "itsdangerous", "python_multipart", "psutil"):
        try:
            __import__(mod)
            add(f"dependency {mod}", "ok")
        except ImportError:
            add(f"dependency {mod}", "fail", "missing: run install.sh (or pip install -r requirements.txt)")
    ff = shutil.which("ffmpeg", path=os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin")
    if not ff:
        add("ffmpeg", "fail", "not found: brew install ffmpeg (needed for thumbnails and browser-compatible previews)")
    else:
        enc = _sh(ff, "-hide_banner", "-encoders")
        add("ffmpeg", "ok" if "libx264" in enc else "warn", ff + ("" if "libx264" in enc else " (no libx264: previews will not be generated)"))
    app = h3capp_app_path()
    add("H3cApp app", "ok" if app else "warn", f"{app} v{h3capp_version()}" if app else "not found in /Applications or ~/Applications (set H3C_APP_PATH). Install from https://github.com/JunzoKamahara/H3cApp/releases")
    running = bool(_sh(sys_bin("pgrep"), "-x", "H3cApp"))
    add("H3cApp running", "ok" if running else "warn", "yes" if running else "no: open H3cApp once so it creates its API token")
    add("H3cApp token", "ok" if TOKEN_FILE.exists() else "warn", "present" if TOKEN_FILE.exists() else f"missing ({TOKEN_FILE}); created by H3cApp when it starts")
    if TOKEN_FILE.exists():
        st = _api("/api/status")
        if isinstance(st, dict):
            add("H3cApp API", "ok", f"engine: {st.get('engine_state')}, device: {st.get('device')}")
            models = _api("/api/models")
            n = len(models) if isinstance(models, list) else 0
            add("H3 models", "ok" if n else "warn", f"{n} registered" if n else "none registered: add/import a model in H3cApp (see docs/MODELS.md)")
        else:
            add("H3cApp API", "warn", str(st))
    data = ROOT / "data"
    add("data directory", "ok" if (data / "config.json").exists() else "info",
        "configured" if (data / "config.json").exists() else "not created yet: run bin/h3studio setup")
    free = shutil.disk_usage(ROOT).free / 1e9
    add("disk free", "ok" if free > 50 else "warn", f"{free:.0f} GB (models and videos are large)")
    add("macmon (optional)", "ok" if shutil.which("macmon") else "info", "found" if shutil.which("macmon") else "not installed: temperature/power tiles will show '—' (brew install macmon)")
    ts = shutil.which("tailscale")
    add("tailscale (optional)", "info", "installed; remote access is optional (bin/h3studio tailscale-on)" if ts else "not installed; H3 Studio is local-only by default")
    return res


def main() -> int:
    res = run_checks()
    if "--json" in sys.argv:
        print(json.dumps(res, indent=2))
    else:
        mark = {"ok": "ok  ", "info": "info", "warn": "WARN", "fail": "FAIL"}
        for r in res:
            print(f"[{mark[r['status']]}] {r['name']:<24} {r['detail']}")
    return 1 if any(r["status"] == "fail" for r in res) else 0


if __name__ == "__main__":
    raise SystemExit(main())
