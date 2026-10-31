"""Runtime configuration: ``data/config.json`` (mode 0600, directory 0700, never committed).

Created on first use with a random password and session secret. The CLI (`bin/h3studio`) uses the same functions, so
`password`, `setup` and `tailscale-on` work without starting the server.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {
    "compute_mode": "resident",      # fallback for jobs created without an explicit mode
    "secure_cookie": False,          # true when served over HTTPS (e.g. Tailscale Serve); off keeps http://127.0.0.1 working
    "enable_ssd_streaming": False,   # offer H3cApp's low-memory SSD streaming mode (not verified by this project)
    "min_free_disk_gb": 15,          # refuse new jobs below this much free disk
    "min_free_mem_pct": 20,          # defer starting a job below this macOS memory-free level
    "allowed_ts_users": [],          # optional Tailscale-User-Login allow-list (see docs/SECURITY-MODEL.md)
}


def data_dir() -> Path:
    return Path(os.environ.get("H3STUDIO_DATA", ROOT / "data"))


def config_path() -> Path:
    return data_dir() / "config.json"


def _write(cfg: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(p.parent, 0o700)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def load_config() -> dict:
    """Return the config, creating it (with fresh secrets) on first run and filling in keys added by newer versions."""
    p = config_path()
    if p.exists():
        cfg = json.loads(p.read_text())
        missing = {k: v for k, v in DEFAULTS.items() if k not in cfg}
        if missing:
            cfg.update(missing)
            _write(cfg)
        return cfg
    cfg = {"password": secrets.token_urlsafe(12), "session_secret": secrets.token_hex(32), **DEFAULTS}
    _write(cfg)
    return cfg


def set_value(key: str, value) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"unknown config key: {key}")
    cfg = load_config()
    cfg[key] = value
    _write(cfg)


def rotate_secrets() -> str:
    """New password and session secret (logs everyone out). Returns the new password."""
    cfg = load_config()
    cfg["password"], cfg["session_secret"] = secrets.token_urlsafe(12), secrets.token_hex(32)
    _write(cfg)
    return cfg["password"]


if __name__ == "__main__":      # python -m app.config password|init|rotate|set KEY VALUE(json)
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"
    if cmd == "password":
        print(load_config()["password"])
    elif cmd == "init":
        existed = config_path().exists()
        cfg = load_config()
        print(("existing" if existed else "created") + f" {config_path()}")
        if not existed:
            print("password: " + cfg["password"])
    elif cmd == "rotate":
        print(rotate_secrets())
    elif cmd == "set" and len(sys.argv) == 4:
        set_value(sys.argv[2], json.loads(sys.argv[3]))
        print("ok")
    else:
        raise SystemExit("usage: python -m app.config init|password|rotate|set KEY JSON_VALUE")
