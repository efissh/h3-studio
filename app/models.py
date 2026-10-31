"""ModelManager: stable model ids for whatever models are registered in H3cApp.

Nothing here is tied to a particular model, machine or folder layout. The browser only ever sends a ``model_id``
taken from ``GET /api/models``; H3cApp's own UUIDs are resolved server-side and file-system paths never come from
the client. Switching is verified three ways: the ``select`` response, ``GET /api/models`` (active flag) and the
model/cache files the H3cApp process really has mapped (``lsof``).

A model that disappears from H3cApp keeps its history (jobs store a snapshot) but can never be selected, retried
or silently replaced by another model.
"""
from __future__ import annotations

import os
import plistlib
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from typing import Callable, Optional

from .util import sys_bin

# Where H3cApp keeps its token and INT8 caches. Override for non-default installs.
SUPPORT_DIR = Path(os.environ.get("H3C_SUPPORT_DIR", Path.home() / "Library/Application Support/H3cApp"))
APP_CANDIDATES = [Path("/Applications/H3cApp.app"), Path.home() / "Applications/H3cApp.app"]

MODE_LABELS = {
    "resident": "Resident 常驻(无缓存)",
    "attentionCache": "Fast INT8 缓存",
    "ssdStreaming": "SSD 流式(低内存)",
}
MODE_NOTES = {
    "resident": "整个 DiT 常驻统一内存,不需要缓存,占用内存最大。",
    "attentionCache": "读取 H3cApp 预先构建的 INT8 缓存;需要 M5 级 GPU,且该模型的缓存已在 H3cApp 内构建。",
    "ssdStreaming": "按需从 SSD 流式读取权重,内存占用最小,速度最慢;由 H3cApp 提供,本项目未做性能验证。",
}


class ModelError(Exception):
    """Lookup / switch failure. Never swallowed into a fallback model."""


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:48] or "model"


def h3capp_app_path() -> Optional[Path]:
    env = os.environ.get("H3C_APP_PATH")
    for p in ([Path(env)] if env else []) + APP_CANDIDATES:
        if (p / "Contents/Info.plist").exists():
            return p
    return None


def h3capp_version() -> str:
    p = h3capp_app_path()
    try:
        return plistlib.loads((p / "Contents/Info.plist").read_bytes()).get("CFBundleShortVersionString", "?") if p else "?"
    except Exception:
        return "?"


def _dir_bytes(p: Path) -> int:
    tot = 0
    for f in p.rglob("*"):
        try:
            if f.is_file() and ".downloads" not in f.parts:
                tot += f.stat().st_size
        except OSError:
            pass
    return tot


class ModelManager:
    def __init__(self, call: Callable, last_test: Optional[Callable[[str], Optional[float]]] = None,
                 enable_ssd_streaming: bool = False, api_url: Optional[str] = None):
        self._call = call                    # call(method, path, **kw) -> httpx.Response
        self._last_test = last_test or (lambda mid: None)
        self._ssd = enable_ssd_streaming
        self._port = urlparse(api_url or os.environ.get("H3C_API_URL", "http://127.0.0.1:8420")).port or 8420
        self._lock = threading.Lock()
        self._detail_cache: dict = {}
        self._size_cache: dict = {}
        self._version = h3capp_version()

    # -- discovery ---------------------------------------------------------
    def _raw(self) -> list:
        r = self._call("GET", "/api/models")
        if r.status_code != 200:
            raise ModelError(f"GET /api/models HTTP {r.status_code}")
        return list(r.json())

    def _index(self, raw: Optional[list] = None) -> dict:
        """model_id -> H3cApp entry. ids are derived from the folder name, so they survive re-imports."""
        out: dict = {}
        for m in (raw if raw is not None else self._raw()):
            mid = "m-" + slug(Path(m["path"]).name)
            if mid in out:                                  # two folders with the same name: disambiguate stably
                mid = f"{mid}-{str(m['id'])[:6].lower()}"
            out[mid] = m
        return out

    def _detail(self, h3_id: str) -> dict:
        """Parsed H3cApp model detail (cached 10 s): INT8 cache state and component descriptions."""
        c = self._detail_cache.get(h3_id)
        if c and time.time() - c[0] < 10:
            return c[1]
        info = {"supported": False, "built": False, "cache_bytes": None, "cache_text": "未知",
                "dit": None, "text_encoder": None, "ref2va": False}
        try:
            r = self._call("GET", f"/api/models/detail?id={h3_id}")
            for sec in r.json().get("sections", []):
                for row in sec.get("rows", []):
                    title, lines = row.get("title", "").lower(), row.get("lines", [])
                    text = " ".join(lines)
                    if title.startswith("fast mode") and "int8" in title:
                        info["supported"] = "unsupported" not in text.lower() and "not available" not in text.lower()
                    elif title.startswith("int8 cache (fl2va)"):
                        info["built"] = row.get("status") == "ok"
                        m = re.match(r"([\d.]+)\s*(GB|MB)", text)
                        if info["built"] and m:
                            info["cache_bytes"] = int(float(m.group(1)) * (1e9 if m.group(2) == "GB" else 1e6))
                        info["cache_text"] = ("已构建 " + text) if info["built"] else "未构建(M5 支持,需在 H3cApp 内构建)"
                    elif title == "dit" and lines:
                        info["dit"] = lines[0][:100]
                    elif title == "text encoder" and lines:
                        info["text_encoder"] = lines[0][:100]
                    elif title.startswith("from reference images"):
                        info["ref2va"] = row.get("status") == "ok"
        except Exception:       # a failed/odd detail reply just leaves "unknown / not built": never an assumption in the other direction
            pass
        self._detail_cache[h3_id] = (time.time(), info)
        return info

    def _size(self, path: Path) -> int:
        c = self._size_cache.get(path)
        if c and time.time() - c[0] < 120:
            return c[1]
        n = _dir_bytes(path) if path.is_dir() else 0
        self._size_cache[path] = (time.time(), n)
        return n

    def _modes(self, d: dict) -> list:
        modes = ["resident"]
        if d["built"] and d["supported"]:
            modes.append("attentionCache")
        if self._ssd:
            modes.append("ssdStreaming")
        return modes

    def list(self) -> list:
        try:
            idx = self._index()
            up = True
        except Exception:
            idx, up = {}, False
        out = []
        for mid, m in idx.items():
            d = self._detail(m["id"])
            modes = self._modes(d)
            default = "attentionCache" if "attentionCache" in modes else "resident"
            fmt = "safetensors" if (d["dit"] or "").lower().startswith("safetensors") else "gguf"
            out.append({
                "id": mid, "display_name": m.get("name") or Path(m["path"]).name, "engine": "h3capp",
                "path_name": Path(m["path"]).name,
                "quantization": " · ".join(x for x in (f"DiT {d['dit']}" if d["dit"] else "",
                                                        f"Text encoder {d['text_encoder']}" if d["text_encoder"] else "") if x) or "—",
                "installed": True, "available": up,
                "active": bool(m.get("active")), "loaded": bool(m.get("active")),
                "supported_features": ["t2v", "i2v", "fl2v"], "ref2va_installed": d["ref2va"],
                "defaults": {"steps": 20, "speed_mode": "quality", "seconds": 5},
                "supports_int8_cache": d["supported"], "cache_built": d["built"], "cache_bytes": d["cache_bytes"],
                "cache_status": d["cache_text"], "dit_format": fmt,
                "compute_modes": modes, "default_compute_mode": default, "default_mode_available": True,
                "mode_labels": {k: MODE_LABELS[k] for k in modes},
                "mode_stats": {k: {"note": MODE_NOTES[k]} for k in modes},
                "estimated_disk_usage": self._size(Path(m["path"])),
                "disk_note": "目录内文件大小合计(APFS 克隆共享的数据块不会真正占用两份空间)",
                "last_test_seconds": self._last_test(mid),
                "h3capp_version": self._version,
            })
        return out

    def default_id(self) -> Optional[str]:
        """The active model if usable, else the first available one."""
        ms = [m for m in self.list() if m["available"]]
        for m in ms:
            if m["active"]:
                return m["id"]
        return ms[0]["id"] if ms else None

    def get(self, model_id: str) -> dict:
        for m in self.list():
            if m["id"] == model_id:
                return m
        raise ModelError(f"模型不可用或已不存在: {model_id}(历史记录仍可查看,但不会改用其他模型)")

    def display(self, model_id: str) -> str:
        try:
            return self.get(model_id)["display_name"]
        except ModelError:
            return model_id

    def validate_choice(self, model_id) -> dict:
        if not isinstance(model_id, str) or not re.fullmatch(r"m-[a-z0-9-]{1,60}", model_id):
            raise ModelError("无效的模型 ID")
        m = self.get(model_id)
        if not m["available"]:
            raise ModelError(f"模型不可用: {m['display_name']}(H3cApp 离线)")
        return m

    def validate_mode(self, model_id: str, mode) -> str:
        m = self.get(model_id)
        mode = mode or m["default_compute_mode"]
        if mode not in m["compute_modes"]:
            raise ModelError(f"计算模式「{mode}」对 {m['display_name']} 不可用(当前可用: {', '.join(m['compute_modes']) or '无'})")
        return mode

    def snapshot(self, model_id: str) -> dict:
        m = self.get(model_id)
        return {"id": m["id"], "display": m["display_name"], "folder": m["path_name"], "engine": "h3capp",
                "quantization": m["quantization"], "dit_format": m["dit_format"], "h3capp_version": self._version}

    # -- switching ---------------------------------------------------------
    def ensure_active(self, model_id: str) -> dict:
        """Make `model_id` the active H3cApp model and prove it. Caller guarantees the GPU is idle."""
        with self._lock:
            idx = self._index()
            h = idx.get(model_id)
            if not h:
                raise ModelError(f"H3cApp 中找不到模型「{model_id}」(不会改用其他模型)")
            if not h.get("active"):
                r = self._call("POST", "/api/models/select", json={"id": h["id"]}, timeout=120)
                if r.status_code != 200:
                    try:
                        msg = r.json().get("error", r.text)
                    except Exception:
                        msg = r.text
                    raise ModelError(f"H3cApp 拒绝切换: {msg}"[:300])
            actives = [mid for mid, m in self._index().items() if m.get("active")]
            if actives != [model_id]:
                raise ModelError(f"切换后激活模型不符: 期望「{model_id}」,实际 {actives}")
            return self.snapshot(model_id)

    def _engine_pid(self) -> Optional[str]:
        """PID of the process that really serves the API port, but only if it is H3cApp.

        Looking the process up by name would inspect the wrong process whenever the API URL points somewhere else
        (a mock engine, a tunnel, a second instance). Anything that is not H3cApp yields None = "cannot verify".
        """
        try:
            out = subprocess.run([sys_bin("lsof"), "-nP", f"-iTCP:{self._port}", "-sTCP:LISTEN", "-Fpc"],
                                 capture_output=True, text=True, timeout=10).stdout
        except Exception:
            return None
        pid = name = None
        for line in out.splitlines():
            if line.startswith("p"):
                pid = line[1:]
            elif line.startswith("c") and pid:
                name = line[1:]
                if name == "H3cApp":
                    return pid
        return None

    def verify_loaded(self, model_id: str) -> Optional[bool]:
        """Check what the H3cApp process really has mapped.

        Model files (.gguf/.safetensors) under any registered model folder must all belong to the selected model, and
        an INT8 cache file, if mapped, must belong to that model's UUID. True = consistent and something was seen;
        False = a file of another model/cache is mapped; None = nothing conclusive (yet).
        """
        try:
            idx = self._index()
            target = idx.get(model_id)
            if not target:
                return None
            pid = self._engine_pid()
            if not pid:
                return None
            out = subprocess.run([sys_bin("lsof"), "-p", pid, "-Fn"], capture_output=True, text=True, timeout=20).stdout
        except Exception:
            return None
        roots = {mid: str(Path(m["path"]).resolve()) + "/" for mid, m in idx.items()}
        cache_root = str(SUPPORT_DIR / "cache") + "/"
        seen, caches = set(), set()
        for line in out.splitlines():
            if not line.startswith("n"):
                continue
            path = line[1:]
            if path.endswith((".gguf", ".safetensors")):
                for mid, root in roots.items():
                    if path.startswith(root):
                        seen.add(mid)
            elif path.startswith(cache_root) and path.endswith(".cache"):
                caches.add(path[len(cache_root):].split("/", 1)[0])
        if (seen and seen != {model_id}) or (caches and caches != {str(target["id"])}):
            return False
        return True if (seen or caches) else None
