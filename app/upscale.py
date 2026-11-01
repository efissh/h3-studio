"""Standalone H3cApp video enlargement, independent of the H3 generation model.

Browser uploads stay in the private H3 Studio data directory; the H3cApp API
receives server-generated absolute paths only. H3cApp must run on this Mac.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from fastapi import Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

MAX_UPLOAD = 1024 * 1024 * 1024  # 1 GiB, streamed rather than held in memory
METHODS = {"standard", "metalFX", "realESRGANGeneral", "realESRGANAnime",
           "swiftVR", "swiftVRFourX"}
SCALES = (1.5, 2, 3, 4)
ID = re.compile(r"^[0-9a-f]{32}$")


def register(app, *, data_dir, authed, engine_call, engine_status, ffprobe,
             min_free_disk_gb=15):
    root = Path(data_dir) / "upscale"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    lock = threading.RLock()
    jobs = {}

    def save(job):
        """Metadata is private and atomically replaced; the browser never sees paths."""
        folder = root / job["id"]
        path, tmp = folder / "job.json", folder / "job.json.tmp"
        tmp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    def update(jid, **changes):
        with lock:
            job = jobs[jid]
            job.update(changes)
            save(job)
            return dict(job)

    def public(job):
        return {k: v for k, v in job.items() if k not in
                ("extension", "cancel_requested", "started_at")}

    def find(jid):
        if not ID.fullmatch(jid):
            raise HTTPException(404, "任务不存在")
        with lock:
            job = jobs.get(jid)
            if job is None:
                raise HTTPException(404, "任务不存在")
            return dict(job)

    for f in root.glob("*/job.json"):
        try:
            job = json.loads(f.read_text(encoding="utf-8"))
            if not ID.fullmatch(job["id"]) or f.parent.name != job["id"]:
                continue
            if job["status"] == "running":
                job["status"] = "failed"
                job["error"] = "服务重启，未能接管超分任务；请确认 H3cApp 已空闲后重新上传"
                save(job)
            jobs[job["id"]] = job
        except (OSError, ValueError, KeyError, TypeError):
            continue

    def execute(jid):
        job = find(jid)
        folder = root / jid
        source = folder / ("source" + job["extension"])
        output = folder / "enhanced.mp4"
        started = time.monotonic()
        accepted = False
        cancelled_once = False
        last_ok = started
        seen_running = False
        try:
            if find(jid).get("cancel_requested"):
                update(jid, status="cancelled", error="已取消")
                return
            resp = engine_call("POST", "/api/upscale-file",
                               json={"path": str(source), "output": str(output),
                                     "upscaler": job["method"], "scale": job["scale"]})
            if resp.status_code not in (200, 202):
                try:
                    reason = resp.json().get("error", resp.text)
                except (ValueError, AttributeError):
                    reason = resp.text
                raise RuntimeError("H3cApp HTTP %s: %s" % (resp.status_code, str(reason)[:250]))
            accepted = True
            while time.monotonic() - started < 6 * 3600:
                time.sleep(2)
                current = find(jid)
                if current.get("cancel_requested") and accepted and not cancelled_once:
                    cancelled_once = True
                    try:
                        engine_call("POST", "/api/upscale/cancel")
                    except Exception:
                        pass
                try:
                    status = engine_status()
                    last_ok = time.monotonic()
                except Exception:
                    if time.monotonic() - last_ok > 120:
                        raise RuntimeError("H3cApp 已失联超过两分钟，请检查引擎状态")
                    continue
                running = bool(status.get("upscaling_video"))
                seen_running = seen_running or running
                if running:
                    progress = status.get("upscale_progress") or 0
                    try:
                        progress = max(0.0, min(float(progress), 1.0))
                    except (ValueError, TypeError):
                        progress = 0.0
                    update(jid, progress=progress, message=str(status.get("message") or "正在超分…")[:200])
                    continue
                # H3cApp writes to a temporary file and atomically renames on success.
                if output.is_file() and output.stat().st_size > 1024:
                    if current.get("cancel_requested"):
                        update(jid, status="cancelled", error="已取消")
                    else:
                        update(jid, status="done", progress=1, message="完成", finished_at=time.time())
                    return
                if current.get("cancel_requested") and cancelled_once and seen_running:
                    update(jid, status="cancelled", error="已取消")
                    return
                if seen_running or time.monotonic() - started > 45:
                    raise RuntimeError(str(status.get("message") or "H3cApp 未产出高清视频")[:250])
            raise RuntimeError("超分任务超时")
        except Exception as exc:
            update(jid, status="failed", error=str(exc)[:350])
        finally:
            with lock:
                if active["id"] == jid:
                    active["id"] = None

    active = {"id": None}

    @app.get("/api/upscale/methods", dependencies=[Depends(authed)])
    async def upscale_methods():
        try:
            r = await asyncio.to_thread(engine_call, "GET", "/api/upscalers")
            if r.status_code != 200:
                raise RuntimeError("HTTP %d" % r.status_code)
            result = r.json()
            entries = result if isinstance(result, list) else (
                result.get("upscalers") or result.get("methods") or [])
            return {"methods": [
                {"id": m.get("id"), "label": m.get("label", m.get("id")),
                 "available": bool(m.get("available")), "reason": m.get("reason", "")}
                for m in entries if isinstance(m, dict) and m.get("id") in METHODS]}
        except Exception as exc:
            return {"methods": [], "error": "无法读取 H3cApp 超分功能: " + str(exc)[:120]}

    @app.post("/api/upscale/upload", dependencies=[Depends(authed)])
    async def upscale_upload(file: UploadFile = File(...)):
        filename = Path(file.filename or "video.mp4").name
        ext = Path(filename).suffix.lower()
        if ext not in (".mp4", ".mov", ".m4v"):
            raise HTTPException(415, "仅支持 MP4、MOV 和 M4V")
        if shutil.disk_usage(root).free / 1e9 < min_free_disk_gb:
            raise HTTPException(507, "磁盘剩余空间不足")
        jid = uuid.uuid4().hex
        folder = root / jid
        folder.mkdir(mode=0o700)
        source = folder / ("source" + ext)
        size = 0
        try:
            with source.open("xb") as stream:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "上传文件不能超过 1 GiB")
                    stream.write(chunk)
            with source.open("rb") as stream:
                magic = stream.read(16)
            if len(magic) < 12 or magic[4:8] != b"ftyp":
                raise HTTPException(415, "不是有效的 MP4/MOV 视频容器")
            result = await asyncio.to_thread(
                subprocess.run, [ffprobe, "-v", "error", "-select_streams", "v:0",
                                 "-show_entries", "stream=width,height",
                                 "-of", "json", str(source)],
                capture_output=True, text=True, timeout=30, check=False)
            streams = json.loads(result.stdout or "{}").get("streams") or []
            if result.returncode or not streams:
                raise HTTPException(415, "未检测到可识别的视频画面")
            width, height = int(streams[0]["width"]), int(streams[0]["height"])
            if width < 1 or height < 1 or width > 4096 or height > 4096:
                raise HTTPException(400, "视频分辨率超出支持范围")
            job = {"id": jid, "name": filename[:120], "extension": ext, "bytes": size,
                   "width": width, "height": height, "status": "uploaded",
                   "method": "realESRGANGeneral", "scale": 2,
                   "progress": 0, "message": "", "error": "",
                   "created_at": time.time(), "finished_at": None,
                   "cancel_requested": False}
            with lock:
                jobs[jid] = job
                save(job)
            return public(job)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        finally:
            await file.close()

    @app.get("/api/upscale/jobs", dependencies=[Depends(authed)])
    async def upscale_jobs():
        with lock:
            return {"jobs": [public(j) for j in
                    sorted(jobs.values(), key=lambda j: j["created_at"], reverse=True)[:100]]}

    @app.post("/api/upscale/jobs/{jid}/start", dependencies=[Depends(authed)])
    async def upscale_start(jid: str, request: Request):
        body = await request.json()
        method, scale = body.get("method"), body.get("scale")
        if method not in METHODS or type(scale) not in (float, int) or scale not in SCALES:
            raise HTTPException(400, "超分方式或倍率不正确")
        job = find(jid)
        if max(job["width"] * scale, job["height"] * scale) > 4096:
            raise HTTPException(400, "放大后任一边不能超过 4096 像素")
        if shutil.disk_usage(root).free / 1e9 < min_free_disk_gb:
            raise HTTPException(507, "磁盘剩余空间不足")
        with lock:
            if active["id"] is not None:
                raise HTTPException(409, "已有超分任务正在进行")
            if jobs[jid]["status"] != "uploaded":
                raise HTTPException(409, "该任务不能重复启动，请重新上传视频")
            active["id"] = jid
            update(jid, status="running", method=method, scale=scale,
                   started_at=time.time(), progress=0, cancel_requested=False)
        threading.Thread(target=execute, args=(jid,), daemon=True, name="upscale-worker").start()
        return {"id": jid, "ok": True}

    @app.post("/api/upscale/jobs/{jid}/cancel", dependencies=[Depends(authed)])
    async def upscale_cancel(jid: str):
        find(jid)
        with lock:
            if active["id"] != jid or jobs[jid]["status"] != "running":
                raise HTTPException(409, "任务不在运行中")
            update(jid, cancel_requested=True, message="正在取消…")
        return {"ok": True}

    @app.get("/api/upscale/jobs/{jid}/{kind}", dependencies=[Depends(authed)])
    async def upscale_media(jid: str, kind: str, download: int = 0):
        job = find(jid)
        if kind not in ("source", "enhanced"):
            raise HTTPException(404)
        if kind == "enhanced" and job["status"] != "done":
            raise HTTPException(404)
        path = root / jid / (("source" + job["extension"]) if kind == "source" else "enhanced.mp4")
        if not path.is_file() or root.resolve() not in path.resolve().parents:
            raise HTTPException(404)
        filename = ("upscaled_" if kind == "enhanced" else "original_") + jid[:8] + (".mp4" if kind == "enhanced" else job["extension"])
        return FileResponse(path, media_type="video/quicktime" if kind == "source" and job["extension"] == ".mov" else "video/mp4",
                            filename=filename if download else None,
                            content_disposition_type="attachment" if download else "inline")

    @app.delete("/api/upscale/jobs/{jid}", dependencies=[Depends(authed)])
    async def upscale_delete(jid: str):
        find(jid)
        with lock:
            if active["id"] == jid or jobs[jid]["status"] == "running":
                raise HTTPException(409, "请先取消正在进行的任务")
            jobs.pop(jid)
        shutil.rmtree(root / jid, ignore_errors=True)
        return {"ok": True}
