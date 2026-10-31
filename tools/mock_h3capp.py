#!/usr/bin/env python3
"""A tiny stand-in for H3cApp's local API, for demos, development and CI. No GPU, no model, no H3cApp needed.

    python3 tools/mock_h3capp.py [--dir DIR] [--port 8421] [--seconds 6]

It writes a bearer token to <dir>/api-token and serves the subset of the H3cApp API that H3 Studio uses on 127.0.0.1.
Point H3 Studio at it with:
    H3C_API_URL=http://127.0.0.1:8421  H3C_TOKEN_FILE=<dir>/api-token   (the script prints the exact path)

"Generating" just walks through the usual stages for a few seconds and then synthesises a test-pattern MP4 with
ffmpeg (video + sine audio). It is NOT a model: output is never related to the prompt.
"""
from __future__ import annotations

import argparse
import tempfile
import json
import secrets
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SIZES = {"small": 256, "medium": 384, "large": 512}


class State:
    def __init__(self, base: Path, seconds: float):
        self.lock = threading.Lock()
        self.base, self.run_seconds = base, seconds
        self.token = secrets.token_urlsafe(24)
        self.models = []
        for i, (name, built) in enumerate((("Demo Model A", True), ("Demo Model B", False))):
            p = base / "Imported" / name
            (p / "FL2VA").mkdir(parents=True, exist_ok=True)
            self.models.append({"id": f"00000000-0000-4000-8000-00000000000{i + 1}", "name": name, "path": str(p),
                                "active": i == 0, "_built": built})
        self.generating, self.cancel, self.result = False, False, None
        self.phase, self.stage, self.detail, self.progress = "", "", "", 0.0
        self.started, self.message = 0.0, None

    def status(self) -> dict:
        el = (time.time() - self.started) if self.generating else 0
        eta = max(0.0, self.run_seconds - el) if self.generating else None
        return {"engine_state": "ready", "device": "Mock Apple GPU (demo)", "is_generating": self.generating,
                "is_cancelling": self.generating and self.cancel, "elapsed_seconds": el, "estimated_remaining_seconds": eta,
                "phase": self.phase, "stage_title": self.stage, "stage_detail": self.detail, "progress": self.progress,
                "result_available": self.result is not None and not self.generating, "message": self.message}

    def detail_doc(self, m: dict) -> dict:
        built = m["_built"]
        rows_can = [{"title": "From text, first and last images", "status": "ok", "lines": ["Available (FL2VA)"]},
                    {"title": "Fast mode (M5 int8 cache)", "status": "ok" if built else "info",
                     "lines": ["Available: the cache is built" if built else "Available after “Build Cache…” in Advanced Settings (M5 only)"]}]
        return {"name": m["name"], "path": m["path"], "sections": [
            {"title": "What this model can do", "rows": rows_can},
            {"title": "FL2VA", "rows": [{"title": "DiT", "status": "ok", "lines": ["GGUF · Q8_0 · 21.44 GB (mock)"]},
                                         {"title": "Text encoder", "status": "ok", "lines": ["GGUF · Q8_0 · 27.49 GB (mock)"]}]},
            {"title": "Caches", "rows": [{"title": "int8 cache (FL2VA)", "status": "ok" if built else "info",
                                          "lines": ["19.28 GB" if built else "Not built yet"]}]}]}

    def run(self, body: dict) -> None:
        """Simulated generation worker."""
        steps = int(body.get("steps", 20))
        stages = [("Preparing", "Loading the model"), ("Denoising", "step"), ("Decoding to video", "Decoding"), ("Writing the video file", "")]
        t0 = time.time()
        while True:
            el = time.time() - t0
            frac = min(1.0, el / self.run_seconds)
            with self.lock:
                if self.cancel:
                    self.generating, self.phase, self.stage, self.message = False, "Generation canceled", "", None
                    return
                self.progress = frac
                idx = 0 if frac < .1 else (1 if frac < .8 else (2 if frac < .95 else 3))
                self.stage = stages[idx][0]
                self.detail = f"{int(frac * steps)}/{steps} steps" if idx == 1 else stages[idx][1]
                self.phase = self.stage
            if frac >= 1:
                break
            time.sleep(0.25)
        out = self.base / "result.mp4"
        secs = max(1, min(int(body.get("seconds", 2)), 4))
        side = SIZES.get(str(body.get("size_profile", "")).split("-")[-1], 256)
        ff = shutil.which("ffmpeg") or "ffmpeg"
        r = subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={side * 16 // 9 // 2 * 2}x{side}:rate=24:duration={secs}",
                            "-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-shortest", "-metadata", "comment=H3 Studio mock output", str(out)], capture_output=True, text=True)
        with self.lock:
            self.generating = False
            if r.returncode == 0:
                self.result, self.message, self.phase, self.stage = out, None, "Done", "Writing the video file"
            else:
                self.result, self.message = None, "mock: ffmpeg is required to synthesise the result video"


def make_handler(st: State):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):          # quiet
            pass

        def _send(self, code: int, obj=None, raw: bytes = None, ctype="application/json") -> None:
            data = raw if raw is not None else json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _auth(self) -> bool:
            if self.headers.get("Authorization") != f"Bearer {st.token}":
                self._send(401, {"error": "unauthorized"})
                return False
            return True

        def do_GET(self):
            if not self._auth():
                return
            u = urlparse(self.path)
            if u.path == "/api/status":
                return self._send(200, st.status())
            if u.path == "/api/models":
                return self._send(200, [{k: v for k, v in m.items() if not k.startswith("_")} for m in st.models])
            if u.path == "/api/models/detail":
                mid = parse_qs(u.query).get("id", [""])[0]
                m = next((m for m in st.models if m["id"] == mid), None)
                return self._send(200, st.detail_doc(m)) if m else self._send(404, {"error": "no such model"})
            if u.path == "/api/result/video":
                if st.result and st.result.exists():
                    return self._send(200, raw=st.result.read_bytes(), ctype="video/mp4")
                return self._send(404, {"error": "no result"})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._auth():
                return
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad json"})
            p = urlparse(self.path).path
            with st.lock:
                if p == "/api/models/select":
                    if st.generating:
                        return self._send(409, {"error": "a generation is running"})
                    m = next((m for m in st.models if m["id"] == body.get("id")), None)
                    if not m:
                        return self._send(400, {"error": '"id" must be a model id from GET /api/models'})
                    for x in st.models:
                        x["active"] = x is m
                    return self._send(200, {"ok": True})
                if p == "/api/generate":
                    if st.generating:
                        return self._send(409, {"error": "a job is already running"})
                    if not str(body.get("prompt", "")).strip():
                        return self._send(400, {"error": '"prompt" is required'})
                    if body.get("compute_mode") == "attentionCache" and not next(m for m in st.models if m["active"])["_built"]:
                        return self._send(400, {"error": "The int8 cache wasn't found. Build it under “Compute mode” in the advanced settings"})
                    st.generating, st.cancel, st.result, st.message, st.progress, st.started = True, False, None, None, 0.0, time.time()
                    threading.Thread(target=st.run, args=(body,), daemon=True).start()
                    return self._send(202, {"ok": True})
                if p == "/api/cancel":
                    st.cancel = st.generating
                    return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})
    return H


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None, help="state directory (default: a new private temp directory)")
    ap.add_argument("--port", type=int, default=8421)
    ap.add_argument("--seconds", type=float, default=6.0, help="how long a fake generation takes")
    a = ap.parse_args()
    base = Path(a.dir) if a.dir else Path(tempfile.mkdtemp(prefix="h3-mock-"))      # mkdtemp is private (0700) and unpredictable
    base.mkdir(parents=True, exist_ok=True)
    st = State(base, a.seconds)
    tok = base / "api-token"
    tok.write_text(st.token)
    tok.chmod(0o600)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(st))      # loopback only, always
    print(f"mock H3cApp on http://127.0.0.1:{a.port}  token file: {tok}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
