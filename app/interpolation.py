"""Authenticated, opt-in RIFE video interpolation jobs and upgrade notices.

No background upgrade or automatic model installation. The Swift worker and
Python server code are updated only by the operator after validation.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import threading
import time
import urllib.request
import uuid
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse

from .rife_video import Cancelled, interpolate_video

RELEASES = "https://github.com/cinemore/rife-metal/releases"
RELEASE_API = "https://api.github.com/repos/cinemore/rife-metal/releases/latest"
PINNED_ENGINE = "0.1.8"
JOB_ID = re.compile(r"^[0-9a-f]{32}$")

def version_tuple(s):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(map(int, match.groups())) if match else None

def latest_release(fetch=None):
    """Query only the fixed upstream endpoint. Never download or execute a release."""
    if fetch is None:
        def fetch():
            req = urllib.request.Request(
                RELEASE_API, headers={"User-Agent": "H3Studio-RIFE-Version-Check",
                                      "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=4) as r:
                if r.status != 200 or int(r.headers.get("Content-Length") or 0) > 131072:
                    raise ValueError("Invalid release response")
                return json.loads(r.read(131072))
    result = fetch()
    tag = result.get("tag_name", "")
    version = version_tuple(tag)
    return {"latest": tag if version else None,
            "update_available": bool(version and version > version_tuple(PINNED_ENGINE)),
            "release_url": RELEASES if version else None}

def register(app, *, data_dir, authed, video_for_job, ffmpeg, ffprobe,
             engine_gate=None, generation_busy=lambda: False,
             min_free_disk_gb=15):
    root = Path(data_dir) / "interpolation"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    worker = Path(os.environ.get("H3_RIFE_WORKER") or (
        Path(__file__).resolve().parents[1] /
        "tools/rife_stream/.build/release/h3-rife-stream"))
    engine_gate = engine_gate or threading.RLock()
    lock = threading.RLock()
    wake = threading.Event()
    active = {"id": None}
    jobs = {}
    update_cache = {"ts": 0, "data": None}

    def save(job):
        folder = root / job["id"]
        stage = folder / "job.json.tmp"
        stage.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        os.chmod(stage, 0o600)
        os.replace(stage, folder / "job.json")

    def set_job(jid, **kw):
        with lock:
            jobs[jid].update(kw)
            save(jobs[jid])

    def get_job(jid):
        if not JOB_ID.fullmatch(jid):
            raise HTTPException(404, "Unknown interpolation job")
        with lock:
            if jid not in jobs:
                raise HTTPException(404, "Unknown interpolation job")
            return dict(jobs[jid])

    def visible(job):
        return {k: v for k, v in job.items()
                if k not in ("cancel_requested", "source_file", "started_at")}

    for meta in root.glob("*/job.json"):
        try:
            item = json.loads(meta.read_text(encoding="utf-8"))
            if not JOB_ID.fullmatch(item["id"]) or meta.parent.name != item["id"]:
                continue
            if item["status"] == "running":
                item.update(status="failed", error="Server restarted; retry from the original video")
                save(item)
            jobs[item["id"]] = item
        except (OSError, KeyError, ValueError, TypeError):
            continue

    def busy():
        with lock:
            return active["id"] is not None

    def execute(jid):
        with engine_gate:
            if generation_busy():
                set_job(jid, message="Waiting for H3 generation/upscaling")
                return False
            with lock:
                if jobs[jid]["status"] != "queued":
                    return True
                active["id"] = jid
                set_job(jid, status="running", started_at=time.time(),
                        message="Starting HQ RIFE", progress=0)
        folder = root / jid
        tmp = folder / "work"
        try:
            tmp.mkdir()
            def cancelled():
                return get_job(jid).get("cancel_requested", False)
            def progress(value):
                set_job(jid, progress=round(value, 3),
                        message="Interpolating and encoding video")
            stats = interpolate_video(
                folder / "source.mp4", folder / "interpolated.mp4", tmp,
                ffmpeg=ffmpeg, ffprobe=ffprobe, worker=worker,
                target_fps=get_job(jid)["fps"], cancel=cancelled,
                progress=progress)
            if cancelled():
                raise Cancelled()
            set_job(jid, status="done", message="HQ video ready",
                    progress=1, stats=stats, finished_at=time.time())
        except Cancelled:
            set_job(jid, status="cancelled", error="Cancelled", finished_at=time.time())
        except Exception as e:
            set_job(jid, status="failed", error=str(e)[:280], finished_at=time.time())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            with lock:
                if active["id"] == jid:
                    active["id"] = None
        return True

    def loop():
        while True:
            with lock:
                queued = sorted((j for j in jobs.values() if j["status"] == "queued"),
                                key=lambda j: j["created_at"])
            if not queued:
                wake.wait(4)
                wake.clear()
                continue
            jid = queued[0]["id"]
            try:
                execute(jid)
            except Exception as exc:
                if get_job(jid)["status"] == "queued":
                    set_job(jid, status="failed", error=str(exc)[:200])
            time.sleep(3)

    @app.get("/api/interpolate/status", dependencies=[Depends(authed)])
    async def interpolation_status():
        installed = worker.is_file() and os.access(worker, os.X_OK)
        now = time.monotonic()
        if update_cache["data"] is None or now - update_cache["ts"] > 86400:
            try:
                data = await asyncio.to_thread(latest_release)
            except Exception:
                data = {"latest": None, "update_available": False,
                        "release_url": RELEASES}
            update_cache.update(ts=now, data=data)
        return {"available": installed, "engine_version": PINNED_ENGINE if installed else None,
                "model_version": "4.25" if installed else None,
                "quality": "hq", "default_fps": 60,
                "update": update_cache["data"], "manual_update_only": True}

    @app.get("/api/interpolate/jobs", dependencies=[Depends(authed)])
    async def interpolation_jobs():
        with lock:
            return {"jobs": [visible(j) for j in sorted(
                jobs.values(), key=lambda j: j["created_at"], reverse=True)[:100]]}

    @app.post("/api/interpolate/from-job", dependencies=[Depends(authed)])
    async def interpolation_from_job(request: Request):
        body = await request.json()
        source_id, fps = body.get("job_id"), body.get("fps", 60)
        if type(source_id) is not str or not JOB_ID.fullmatch(source_id):
            raise HTTPException(400, "Invalid source job")
        if type(fps) is not int or fps not in (48, 60):
            raise HTTPException(400, "FPS must be 48 or 60")
        if not worker.is_file() or not os.access(worker, os.X_OK):
            raise HTTPException(503, "RifeMetal worker not installed")
        if shutil.disk_usage(root).free < max(min_free_disk_gb * 10**9, 5 * 1024**3):
            raise HTTPException(507, "Insufficient disk space")
        path = Path(video_for_job(source_id))
        if not path.is_file() or path.stat().st_size > 1024**3:
            raise HTTPException(400, "Unsupported source video size")
        jid = uuid.uuid4().hex
        folder = root / jid
        folder.mkdir(mode=0o700)
        try:
            shutil.copy2(path, folder / "source.mp4")
            job = dict(id=jid, source_job_id=source_id, fps=fps,
                       status="queued", progress=0, message="Queued", error="",
                       created_at=time.time(), finished_at=None, cancel_requested=False)
            with lock:
                jobs[jid] = job
                save(job)
            wake.set()
            return visible(job)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    @app.post("/api/interpolate/jobs/{jid}/cancel", dependencies=[Depends(authed)])
    async def interpolation_cancel(jid: str):
        job = get_job(jid)
        if job["status"] not in ("running", "queued"):
            raise HTTPException(409, "Job not active")
        set_job(jid, cancel_requested=True,
                **({"status": "cancelled"} if job["status"] == "queued" else {}))
        wake.set()
        return {"ok": True}

    @app.get("/api/interpolate/jobs/{jid}/video", dependencies=[Depends(authed)])
    async def interpolation_video(jid: str, download: int = 0):
        job = get_job(jid)
        if job["status"] != "done":
            raise HTTPException(404, "Video not ready")
        path = root / jid / "interpolated.mp4"
        if not path.is_file() or path.resolve().parent != (root / jid).resolve():
            raise HTTPException(404, "Video missing")
        return FileResponse(path, media_type="video/mp4",
                            filename=f"h3_rife_hq_{job['fps']}fps_{jid[:8]}.mp4" if download else None,
                            content_disposition_type="attachment" if download else "inline")

    threading.Thread(target=loop, name="h3-rife-queue", daemon=True).start()
    return {"busy": busy, "jobs": lambda: [visible(j) for j in jobs.values()]}
