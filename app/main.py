"""H3 Studio: FastAPI front for the local H3cApp API (default http://127.0.0.1:8420).

Single FIFO worker, SQLite job store, every finished video persisted to the
library before the next job starts. The H3cApp bearer token is read from disk
per request and never leaves this process.
"""
from __future__ import annotations

import asyncio

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from . import migrations
from .config import load_config
from .util import sys_bin
from .metrics import MetricsSampler
from .models import SUPPORT_DIR, ModelError, ModelManager

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("H3STUDIO_DATA", ROOT / "data"))
LIB = DATA / "library"
UPLOADS = DATA / "uploads"
DB_PATH = DATA / "jobs.sqlite"
CONFIG_PATH = DATA / "config.json"
STATIC = ROOT / "static"
H3_URL = os.environ.get("H3C_API_URL", "http://127.0.0.1:8420")
FFMPEG = shutil.which("ffmpeg", path=os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin") or "ffmpeg"
FFPROBE = shutil.which("ffprobe", path=os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin") or "ffprobe"
TOKEN_FILE = Path(os.environ.get("H3C_TOKEN_FILE", SUPPORT_DIR / "api-token"))

for d in (DATA, LIB, UPLOADS):
    d.mkdir(parents=True, exist_ok=True)
os.chmod(DATA, 0o700)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("h3studio")


# ---------------------------------------------------------------- config
CFG = load_config()


# ---------------------------------------------------------------- db
_db_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA journal_mode=WAL")
_conn.execute(
    """CREATE TABLE IF NOT EXISTS jobs(
    id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at REAL NOT NULL,
    started_at REAL, finished_at REAL, params TEXT NOT NULL, prompt TEXT,
    seed TEXT, stage TEXT, progress REAL DEFAULT 0, eta REAL, error TEXT,
    video_path TEXT, thumb_path TEXT, preview_path TEXT, gen_seconds REAL,
    note TEXT, cancel_requested INTEGER DEFAULT 0, retry_of TEXT)"""
)


migrations.migrate(_conn, DATA)


def q(sql: str, args: tuple = ()) -> list:
    with _db_lock:
        return _conn.execute(sql, args).fetchall()


def x(sql: str, args: tuple = ()) -> None:
    with _db_lock:
        _conn.execute(sql, args)


def job_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["params"] = json.loads(d["params"])
    d["model_info"] = json.loads(d["model_info"]) if d.get("model_info") else None
    d["has_video"] = bool(d["video_path"])
    d["has_preview"] = bool(d["preview_path"])
    for k in ("video_path", "thumb_path", "preview_path"):
        d.pop(k, None)
    return d


# ---------------------------------------------------------------- H3 client
class H3Error(Exception):
    pass


def h3(method: str, path: str, **kw) -> httpx.Response:
    """Call H3cApp; token re-read on every call so an app restart is harmless."""
    for attempt in (1, 2):
        try:
            token = TOKEN_FILE.read_text().strip()
        except OSError:
            raise H3Error("H3cApp 未运行(找不到 api-token)")
        try:
            r = httpx.request(
                method, H3_URL + path, headers={"Authorization": f"Bearer {token}"},
                timeout=kw.pop("timeout", 15), **kw,
            )
        except httpx.HTTPError as e:
            raise H3Error(f"无法连接 H3cApp: {type(e).__name__}")
        if r.status_code == 401 and attempt == 1:
            time.sleep(1)
            continue
        return r
    return r


def h3_status() -> dict:
    r = h3("GET", "/api/status")
    if r.status_code != 200:
        raise H3Error(f"status HTTP {r.status_code}")
    return r.json()


def _last_test(model_id: str):
    r = q("SELECT gen_seconds FROM jobs WHERE model_id=? AND status='done' ORDER BY finished_at DESC LIMIT 1", (model_id,))
    return round(r[0]["gen_seconds"]) if r and r[0]["gen_seconds"] else None


MODELS = ModelManager(h3, _last_test, enable_ssd_streaming=bool(CFG.get("enable_ssd_streaming", False)), api_url=H3_URL)
METRICS = MetricsSampler(ttl=3.0)


# ---------------------------------------------------------------- guards
def free_disk_gb() -> float:
    return shutil.disk_usage(DATA).free / 1e9


def free_mem_pct() -> int:
    try:
        return int(subprocess.check_output([sys_bin("sysctl"), "-n", "kern.memorystatus_level"]).strip())
    except Exception:
        return 100


# ---------------------------------------------------------------- params
SHAPES = {"square", "landscape", "portrait"}
SIZES = {"small", "medium", "large"}
MODES = {"quality", "fast", "fastest"}
UPLOAD_ID = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp)$")


def clean_params(p: dict) -> dict:
    out: dict = {}
    prompt = str(p.get("prompt", "")).strip()
    if not prompt or len(prompt) > 4000:
        raise HTTPException(400, "提示词不能为空且不超过 4000 字")
    out["prompt"] = prompt
    shape, size = str(p.get("shape", "landscape")), str(p.get("size", "medium"))
    if shape not in SHAPES or size not in SIZES:
        raise HTTPException(400, "分辨率无效")
    out["size_profile"] = f"{shape}-{size}" + ("-x2" if p.get("x2") else "")
    try:
        out["seconds"] = int(p.get("seconds", 5))
        out["steps"] = int(p.get("steps", 20))
    except (TypeError, ValueError):
        raise HTTPException(400, "时长或 Steps 无效")
    if not 1 <= out["seconds"] <= 15 or not 3 <= out["steps"] <= 40:
        raise HTTPException(400, "时长须 1–15 秒,Steps 须 3–40")
    mode = str(p.get("speed_mode", "quality"))
    if mode not in MODES:
        raise HTTPException(400, "速度模式无效")
    out["speed_mode"] = mode
    fast_attention = p.get("fast_attention", True)  # M5 Fast mode, separate from INT8 cache
    if type(fast_attention) is not bool:
        raise HTTPException(400, "M5 Fast mode 必须是布尔值")
    out["fast_attention"] = fast_attention
    seed = p.get("seed")
    if seed not in (None, ""):
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            raise HTTPException(400, "Seed 无效")
        if not 0 <= seed < 2**64:
            raise HTTPException(400, "Seed 超出范围")
        out["seed"] = seed
    for key in ("first_frame", "last_frame"):
        v = p.get(key)
        if v:
            if not isinstance(v, str) or not UPLOAD_ID.match(v) or not (UPLOADS / v).is_file():
                raise HTTPException(400, f"{key} 图片无效,请重新上传")
            out[key] = v
    if out.get("last_frame") and not out.get("first_frame"):
        raise HTTPException(400, "尾帧必须配合首帧使用")
    return out


def h3_body(params: dict, seed: int) -> dict:
    body = {
        "prompt": params["prompt"], "size_profile": params["size_profile"],
        "seconds": params["seconds"], "steps": params["steps"],
        "speed_mode": params["speed_mode"], "seed": seed,
        "compute_mode": params.get("compute_mode") or CFG.get("compute_mode", "resident"),
        # An old queued/retried job lacking this field keeps the historical OFF behavior.
        "fast_attention": params.get("fast_attention", False),
    }
    if params.get("first_frame"):
        body["first_frame_path"] = str(UPLOADS / params["first_frame"])
    if params.get("last_frame"):
        body["last_frame_path"] = str(UPLOADS / params["last_frame"])
    return body


# ---------------------------------------------------------------- persistence
def persist_video(job_id: str) -> tuple[str, str]:
    """Download H3 result into the library atomically; returns (video, thumb)."""
    d = LIB / time.strftime("%Y-%m-%d") / job_id
    d.mkdir(parents=True, exist_ok=True)
    tmp, final = d / "original.mp4.part", d / "original.mp4"
    token = TOKEN_FILE.read_text().strip()
    with httpx.stream("GET", H3_URL + "/api/result/video",
                      headers={"Authorization": f"Bearer {token}"}, timeout=120) as r:
        if r.status_code != 200:
            raise H3Error(f"取回视频失败 HTTP {r.status_code}")
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
    if tmp.stat().st_size < 10_000:
        raise H3Error("取回的视频文件异常(过小)")
    os.replace(tmp, final)
    thumb = d / "thumb.jpg"
    try:                                    # thumbnail is best-effort; the saved MP4 is what matters
        for seek in (["-ss", "1"], []):                  # 1 s in; very short clips fall back to the first frame
            subprocess.run([FFMPEG, "-v", "error", "-y", *seek, "-i", str(final),
                            "-frames:v", "1", "-vf", "scale=480:-2", str(thumb)], check=False, timeout=60)
            if thumb.exists() and thumb.stat().st_size > 0:
                break
    except Exception as e:
        log.warning("thumbnail failed: %s", e)
    try:
        pr = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                             "-of", "csv=p=0", str(final)], capture_output=True, text=True, timeout=30).stdout.strip().split(",")
        set_job(job_id, out_w=int(pr[0]), out_h=int(pr[1]))
    except Exception as e:
        log.warning("ffprobe failed: %s", e)
    return str(final), str(thumb) if thumb.exists() else ""


def make_preview(job_id: str, video: str) -> None:
    out = Path(video).with_name("preview.mp4")
    tmp = out.with_suffix(".part.mp4")
    r = subprocess.run([FFMPEG, "-v", "error", "-y", "-i", video, "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(tmp)],
                       timeout=900)
    if r.returncode == 0:
        os.replace(tmp, out)
        x("UPDATE jobs SET preview_path=? WHERE id=?", (str(out), job_id))


# ---------------------------------------------------------------- worker
_wake = threading.Event()


_JOB_COLUMNS = {"status", "started_at", "finished_at", "params", "prompt", "seed", "stage", "progress", "eta", "error", "video_path",
                "thumb_path", "preview_path", "gen_seconds", "note", "cancel_requested", "model_id", "model_info", "out_w", "out_h",
                "verified", "ab_group"}


def set_job(job_id: str, **f) -> None:
    bad = set(f) - _JOB_COLUMNS                       # column names are interpolated into SQL: only known columns, ever
    if bad:
        raise ValueError(f"unknown job column(s): {sorted(bad)}")
    keys = ", ".join(f"{k}=?" for k in f)
    x(f"UPDATE jobs SET {keys} WHERE id=?", (*f.values(), job_id))  # nosec B608: column names are whitelisted above, values are bound


def fail(job_id: str, msg: str, status: str = "failed") -> None:
    set_job(job_id, status=status, error=msg, finished_at=time.time(), stage=None, eta=None)
    log.warning("job %s %s: %s", job_id[:8], status, msg)


def monitor(job_id: str, t0: float) -> None:
    """Follow an H3 job we started (or re-adopted) until it ends."""
    seen_running = False
    mid = q("SELECT model_id FROM jobs WHERE id=?", (job_id,))[0]["model_id"]
    verified = False
    last_ok = time.time()
    while True:
        time.sleep(2)
        row = q("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,))[0]
        if row["cancel_requested"]:
            try:
                h3("POST", "/api/cancel")
            except H3Error:
                pass
        try:
            s = h3_status()
            last_ok = time.time()
        except H3Error as e:
            if time.time() - last_ok > 120:
                return fail(job_id, f"H3cApp 失联超过 2 分钟: {e}")
            continue
        gen = bool(s.get("is_generating"))
        if gen:
            seen_running = True
            if not verified and mid:
                ok = MODELS.verify_loaded(mid)
                if ok is False:
                    try:
                        h3("POST", "/api/cancel")
                    except H3Error:
                        pass
                    return fail(job_id, f"模型校验失败:H3cApp 实际加载的不是「{MODELS.display(mid)}」,任务已中止")
                if ok:
                    verified = True
                    set_job(job_id, verified="api+lsof")
            el, eta = s.get("elapsed_seconds") or 0, s.get("estimated_remaining_seconds")
            frac = s.get("progress")
            if frac is None:
                frac = (el / (el + eta)) if eta is not None and (el + eta) > 0 else 0
            stage = " · ".join(v for v in (s.get("stage_title"), s.get("stage_detail")) if v) or s.get("phase")
            set_job(job_id, stage=stage, progress=float(frac), eta=eta)
            continue
        if not seen_running and time.time() - t0 < 30:
            continue                        # submitted but status not flipped yet
        cancelled = bool(row["cancel_requested"])
        err = s.get("message") if str(s.get("engine_state", "")).startswith("failed") else None
        if str(s.get("engine_state", "")).startswith("failed"):
            err = s.get("engine_state")
        if cancelled:
            return fail(job_id, "已取消", "cancelled")
        if err:
            return fail(job_id, err)
        if not s.get("result_available"):
            return fail(job_id, s.get("message") or "H3cApp 未产出视频")
        if not verified:
            set_job(job_id, verified="api")       # lsof was inconclusive; select + GET /api/models agreed
        try:
            video, thumb = persist_video(job_id)
        except Exception as e:
            return fail(job_id, f"保存视频失败: {e}")
        set_job(job_id, status="done", video_path=video, thumb_path=thumb, progress=1.0, eta=0,
                stage="完成", finished_at=time.time(), gen_seconds=time.time() - t0, note=None)
        log.info("job %s done -> %s", job_id[:8], video)
        threading.Thread(target=make_preview, args=(job_id, video), daemon=True).start()
        return


def worker() -> None:
    # Crash recovery: a job left "running" is either still running in H3 or lost.
    for r in q("SELECT id, started_at FROM jobs WHERE status='running'"):
        try:
            if h3_status().get("is_generating"):
                log.info("re-adopting running job %s", r["id"][:8])
                monitor(r["id"], r["started_at"] or time.time())
                continue
        except H3Error:
            pass
        fail(r["id"], "服务重启时任务中断,可点击重试")
    while True:
        rows = q("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1")
        if not rows:
            _wake.wait(3); _wake.clear()
            continue
        job = rows[0]
        jid, params = job["id"], json.loads(job["params"])
        if job["cancel_requested"]:
            fail(jid, "已取消", "cancelled"); continue
        if free_disk_gb() < CFG["min_free_disk_gb"]:
            set_job(jid, note=f"磁盘剩余 {free_disk_gb():.0f}GB,低于 {CFG['min_free_disk_gb']}GB,暂停启动")
            time.sleep(15); continue
        if free_mem_pct() < CFG["min_free_mem_pct"]:
            set_job(jid, note=f"内存压力高(空闲 {free_mem_pct()}%),等待中")
            time.sleep(15); continue
        try:
            s = h3_status()
        except H3Error as e:
            set_job(jid, note=str(e)); time.sleep(10); continue
        if s.get("is_generating"):
            set_job(jid, note="H3cApp 正忙(可能有手动任务),等待中")
            time.sleep(10); continue
        if not str(s.get("engine_state")) == "ready":
            set_job(jid, note=f"引擎状态: {s.get('engine_state')}"); time.sleep(10); continue
        seed = int(job["seed"]) if job["seed"] else secrets.randbelow(2**32)
        mid = job["model_id"] or MODELS.default_id()
        if not mid:
            fail(jid, "没有可用的模型(请先在 H3cApp 中安装并登记模型)"); continue
        set_job(jid, stage="准备模型…")
        try:
            snap = MODELS.ensure_active(mid)            # GPU is idle here (checked above)
            set_job(jid, model_info=json.dumps(snap, ensure_ascii=False))
        except (ModelError, H3Error, httpx.HTTPError) as e:
            fail(jid, f"模型切换失败(不会自动改用其他模型): {e}"[:500]); continue
        try:
            MODELS.validate_mode(mid, params.get("compute_mode") or "resident")
        except ModelError as e:
            fail(jid, f"计算模式不可用(不会自动改用其他模式): {e}"[:500]); continue
        try:
            r = h3("POST", "/api/generate", json=h3_body(params, seed))
        except H3Error as e:
            set_job(jid, note=str(e)); time.sleep(10); continue
        if r.status_code == 409:
            set_job(jid, note="H3cApp 正忙,等待中"); time.sleep(10); continue
        if r.status_code not in (200, 202):
            try:
                msg = r.json().get("error", r.text)
            except Exception:
                msg = r.text
            fail(jid, f"H3cApp 拒绝任务: {msg}"[:500]); continue
        t0 = time.time()
        set_job(jid, status="running", started_at=t0, seed=str(seed), note=None, stage="启动中")
        try:
            monitor(jid, t0)
        except Exception as e:                      # never let the worker die
            log.exception("monitor crashed")
            fail(jid, f"内部错误: {e}")


# ---------------------------------------------------------------- app
def _secure_cookie() -> bool:
    """Secure cookies need HTTPS. Off by default so plain http://127.0.0.1 works (incl. Safari); `h3studio tailscale-on` turns it on."""
    env = os.environ.get("H3STUDIO_SECURE_COOKIE")
    return (env == "1") if env is not None else bool(CFG.get("secure_cookie", False))


app = FastAPI(title="H3 Studio", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=CFG["session_secret"], session_cookie="h3studio",
                   max_age=14 * 86400, same_site="strict",
                   https_only=_secure_cookie())


@app.middleware("http")
async def guard(request: Request, call_next):
    # Optional Tailnet identity allow-list. The header is only trustworthy when this app listens on loopback and
    # Tailscale Serve is the only way in (see docs/SECURITY-MODEL.md); never expose the port directly with it enabled.
    allowed = CFG.get("allowed_ts_users") or []
    if allowed and request.headers.get("tailscale-user-login") not in allowed:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if request.method in ("POST", "PUT", "DELETE"):
        origin = request.headers.get("origin")
        if origin and origin.split("://", 1)[-1] != request.headers.get("host"):
            return JSONResponse({"error": "bad origin"}, status_code=403)
        if request.headers.get("x-requested-with") != "h3studio":
            return JSONResponse({"error": "csrf"}, status_code=403)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
    return resp


def authed(request: Request) -> None:
    if not request.session.get("ok"):
        raise HTTPException(401, "未登录")


_fails: dict = {}


@app.post("/api/login")
async def login(request: Request):
    ip = request.client.host if request.client else "?"
    n, ts = _fails.get(ip, (0, 0))
    if n >= 5 and time.time() - ts < 300:
        raise HTTPException(429, "尝试过多,请 5 分钟后再试")
    body = await request.json()
    if hmac.compare_digest(str(body.get("password", "")), CFG["password"]):
        _fails.pop(ip, None)
        request.session["ok"] = True
        return {"ok": True}
    _fails[ip] = (n + 1, time.time())
    raise HTTPException(401, "密码错误")


@app.post("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/session")
async def session(request: Request):
    return {"ok": bool(request.session.get("ok"))}


@app.post("/api/upload", dependencies=[Depends(authed)])
async def upload(file: UploadFile = File(...)):
    data = await file.read(15 * 1024 * 1024 + 1)
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "图片不能超过 15MB")
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        ext = "png"
    elif data[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ext = "webp"
    else:
        raise HTTPException(415, "仅支持 PNG / JPEG / WebP")
    name = f"{uuid.uuid4().hex}.{ext}"
    tmp = UPLOADS / (name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, UPLOADS / name)
    return {"id": name}


@app.get("/api/upload/{name}", dependencies=[Depends(authed)])
async def upload_get(name: str):
    if not UPLOAD_ID.match(name) or not (UPLOADS / name).is_file():
        raise HTTPException(404)
    return FileResponse(UPLOADS / name)


def insert_job(params: dict, seed, retry_of=None, model_id: str = "", ab_group=None) -> str:
    if free_disk_gb() < CFG["min_free_disk_gb"]:
        raise HTTPException(507, f"磁盘剩余不足 {CFG['min_free_disk_gb']}GB,已拒绝新任务")
    jid = uuid.uuid4().hex
    x("INSERT INTO jobs(id,status,created_at,params,prompt,seed,retry_of,model_id,ab_group) VALUES(?,?,?,?,?,?,?,?,?)",
      (jid, "queued", time.time(), json.dumps(params, ensure_ascii=False), params["prompt"],
       str(seed) if seed is not None else None, retry_of, model_id, ab_group))
    _wake.set()
    return jid


@app.post("/api/jobs", dependencies=[Depends(authed)])
async def create_job(request: Request):
    body = await request.json()
    params = clean_params(body)
    model_id = pick_model(body.get("model_id"))
    params["compute_mode"] = pick_mode(model_id, body.get("compute_mode"))
    if len(q("SELECT 1 FROM jobs WHERE status IN ('queued','running')")) >= 20:
        raise HTTPException(429, "队列已满(20)")
    return {"id": insert_job(params, params.get("seed"), model_id=model_id)}


def pick_model(model_id) -> str:
    model_id = model_id or MODELS.default_id()
    if not model_id:
        raise HTTPException(400, "没有可用的模型(请先在 H3cApp 中安装并登记模型)")
    try:
        MODELS.validate_choice(model_id)
    except ModelError as e:
        raise HTTPException(400, str(e))
    return model_id


def pick_mode(model_id: str, mode) -> str:
    try:
        return MODELS.validate_mode(model_id, mode)
    except ModelError as e:
        raise HTTPException(400, str(e))


@app.get("/api/models", dependencies=[Depends(authed)])
async def list_models():
    return {"models": MODELS.list(), "default": MODELS.default_id()}


@app.post("/api/jobs/ab", dependencies=[Depends(authed)])
async def create_ab(request: Request):
    """Same prompt/params/seed on several models, queued back to back (FIFO)."""
    body = await request.json()
    params = clean_params(body)
    ids = body.get("model_ids") or []
    if not isinstance(ids, list) or not 2 <= len(ids) <= 3 or len(set(ids)) != len(ids):
        raise HTTPException(400, "A/B 对比需选 2–3 个不同模型")
    ids = [pick_model(m) for m in ids]
    seed = params.get("seed")
    if seed is None:
        seed = secrets.randbelow(2**32)
    group = uuid.uuid4().hex[:12]
    # each model runs in its own default verified compute mode so A/B compares the recommended setups
    modes = {m: pick_mode(m, None) for m in ids}
    return {"group": group, "ids": [insert_job(dict(params, compute_mode=modes[m]), seed, model_id=m, ab_group=group) for m in ids]}


@app.post("/api/jobs/{jid}/retry", dependencies=[Depends(authed)])
async def retry(jid: str, request: Request):
    rows = q("SELECT * FROM jobs WHERE id=?", (jid,))
    if not rows:
        raise HTTPException(404)
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    params = json.loads(rows[0]["params"])
    seed = None if body.get("new_seed") else (rows[0]["seed"] and int(rows[0]["seed"]))
    mid = rows[0]["model_id"]
    if not mid:
        raise HTTPException(409, "该记录没有模型信息,无法重试")
    try:
        MODELS.validate_choice(mid)
    except ModelError as e:
        raise HTTPException(409, f"原模型当前不可用,未改用其他模型: {e}")
    params["compute_mode"] = pick_mode(mid, params.get("compute_mode"))   # old jobs without a mode get the model default
    params["fast_attention"] = params.get("fast_attention", False)  # old job retries preserve pre-feature behavior
    return {"id": insert_job(params, seed, retry_of=jid, model_id=mid)}


@app.post("/api/jobs/{jid}/cancel", dependencies=[Depends(authed)])
async def cancel(jid: str):
    rows = q("SELECT status FROM jobs WHERE id=?", (jid,))
    if not rows:
        raise HTTPException(404)
    st = rows[0]["status"]
    if st == "queued":
        fail(jid, "已取消", "cancelled")
    elif st == "running":
        set_job(jid, cancel_requested=1, stage="正在取消…")
    else:
        raise HTTPException(409, "任务已结束")
    return {"ok": True}


@app.delete("/api/jobs/{jid}", dependencies=[Depends(authed)])
async def delete_job(jid: str):
    rows = q("SELECT status, video_path FROM jobs WHERE id=?", (jid,))
    if not rows:
        raise HTTPException(404)
    if rows[0]["status"] in ("queued", "running"):
        raise HTTPException(409, "请先取消任务")
    if rows[0]["video_path"]:
        shutil.rmtree(Path(rows[0]["video_path"]).parent, ignore_errors=True)
    x("DELETE FROM jobs WHERE id=?", (jid,))
    return {"ok": True}


@app.get("/api/state", dependencies=[Depends(authed)])
async def state():
    try:
        s = h3_status()
        h3s = {"ok": True, "engine": s.get("engine_state"), "device": s.get("device")}
    except H3Error as e:
        h3s = {"ok": False, "error": str(e)}
    active = [job_dict(r) for r in q("SELECT * FROM jobs WHERE status IN ('queued','running') ORDER BY created_at")]
    recent = [job_dict(r) for r in q(
        "SELECT * FROM jobs WHERE status NOT IN ('queued','running') ORDER BY created_at DESC LIMIT 200")]
    metrics = await asyncio.to_thread(METRICS.read)
    return {"h3": h3s, "active": active, "recent": recent,
            "system": {"free_disk_gb": round(free_disk_gb(), 1), "free_mem_pct": free_mem_pct(),
                       "metrics": metrics}}


def media(jid: str, kind: str, mime: str):
    rows = q("SELECT video_path, thumb_path, preview_path, id FROM jobs WHERE id=?", (jid,))
    if not rows:
        raise HTTPException(404)
    r = rows[0]
    path = {"video": r["video_path"], "thumb": r["thumb_path"], "preview": r["preview_path"] or r["video_path"]}[kind]
    if not path or not Path(path).is_file():
        raise HTTPException(404)
    resolved = Path(path).resolve()
    if LIB.resolve() not in resolved.parents:
        raise HTTPException(404)
    return resolved


@app.get("/api/jobs/{jid}/video", dependencies=[Depends(authed)])
async def dl(jid: str, download: int = 0):
    p = media(jid, "video", "video/mp4")
    return FileResponse(p, media_type="video/mp4",
                        filename=f"h3_{p.parent.parent.name}_{jid[:8]}.mp4" if download else None,
                        content_disposition_type="attachment" if download else "inline")


@app.get("/api/jobs/{jid}/preview", dependencies=[Depends(authed)])
async def preview(jid: str):
    return FileResponse(media(jid, "preview", "video/mp4"), media_type="video/mp4")


@app.get("/api/jobs/{jid}/thumb", dependencies=[Depends(authed)])
async def thumb(jid: str):
    return FileResponse(media(jid, "thumb", "image/jpeg"), media_type="image/jpeg")


# Standalone upscaling reuses H3cApp's existing video-file API. It does not
# load MiniMax H3, and the browser never supplies paths to the engine.
from .upscale import register as register_upscale
register_upscale(app, data_dir=DATA, authed=authed,
                 engine_call=lambda *a, **kw: h3(*a, **kw),
                 engine_status=lambda: h3_status(),
                 ffprobe=FFPROBE, min_free_disk_gb=CFG["min_free_disk_gb"])


@app.get("/manifest.webmanifest", include_in_schema=False)
async def pwa_manifest():
    return FileResponse(STATIC / "manifest.webmanifest",
                        media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


@app.get("/pwa/icon-{size}.png", include_in_schema=False)
async def pwa_icon(size: int):
    if size not in (180, 192, 512):
        raise HTTPException(404)
    return FileResponse(STATIC / f"icon-{size}.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


threading.Thread(target=worker, daemon=True, name="h3-worker").start()
