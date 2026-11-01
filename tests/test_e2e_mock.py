"""End-to-end against the mock H3cApp: real server process, real queue, real ffmpeg. Needs ffmpeg; no GPU, no model."""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = shutil.which("ffmpeg", path=os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin")
pytestmark = pytest.mark.skipif(not FFMPEG or "libx264" not in subprocess.run(
    [FFMPEG or "ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout, reason="needs ffmpeg with libx264")
H = {"X-Requested-With": "h3studio"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, proc, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            raise RuntimeError(f"process exited early: {proc.returncode}")
        try:
            httpx.get(url, timeout=1)
            return
        except httpx.HTTPError:
            time.sleep(0.2)
    raise TimeoutError(url)


@pytest.fixture(scope="module")
def stack():
    tmp = Path(tempfile.mkdtemp(prefix="h3studio-e2e-"))
    mport, aport = free_port(), free_port()
    env = dict(os.environ, PATH=os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin", PYTHONDONTWRITEBYTECODE="1")
    mock = subprocess.Popen([sys.executable, str(ROOT / "tools/mock_h3capp.py"), "--dir", str(tmp / "mock"), "--port", str(mport), "--seconds", "2"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    app, applog = None, tmp / "app.log"
    try:
        for _ in range(50):
            if (tmp / "mock/api-token").exists():
                break
            time.sleep(0.1)
        env.update(H3STUDIO_DATA=str(tmp / "data"), H3C_API_URL=f"http://127.0.0.1:{mport}", H3C_TOKEN_FILE=str(tmp / "mock/api-token"),
                   H3STUDIO_SECURE_COOKIE="0")
        (tmp / "data").mkdir()     # CI runners have little free disk/RAM: switch off the resource guards (other keys get defaults)
        (tmp / "data/config.json").write_text(__import__("json").dumps({"password": "e2e-" + "x" * 12, "session_secret": "0" * 64,
                                                                         "min_free_disk_gb": 0, "min_free_mem_pct": 0}))
        app = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(aport)],
                               cwd=ROOT, env=env, stdout=applog.open("wb"), stderr=subprocess.STDOUT)
        wait_http(f"http://127.0.0.1:{aport}/manifest.webmanifest", app)
        pw = __import__("json").loads((tmp / "data/config.json").read_text())["password"]
        c = httpx.Client(base_url=f"http://127.0.0.1:{aport}", headers=H, timeout=20)
        assert c.post("/api/login", json={"password": pw}).status_code == 200
        yield c, tmp
    finally:
        if os.environ.get("E2E_DEBUG") and applog.exists():
            print("--- app log ---\n" + applog.read_text()[-4000:], flush=True)
        for p in (app, mock):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def wait_job(c, jid, until=("done", "failed", "cancelled"), timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = c.get("/api/state").json()
        for j in st["active"] + st["recent"]:
            if j["id"] == jid and j["status"] in until:
                return j
        time.sleep(0.5)
    raise TimeoutError(jid)


def submit(c, **kw) -> str:
    r = c.post("/api/jobs", json=job(**kw))
    assert r.status_code in (200, 201, 202), f"{r.status_code} {r.text}"
    return r.json()["id"]


def job(**kw):
    return {"prompt": "a test prompt", "shape": "landscape", "size": "small", "seconds": 1, "steps": 3, "speed_mode": "quality", **kw}


def test_models_are_discovered_with_real_cache_state(stack):
    c, _ = stack
    d = c.get("/api/models").json()
    by = {m["display_name"]: m for m in d["models"]}
    assert set(by) == {"Demo Model A", "Demo Model B"} and d["default"] == by["Demo Model A"]["id"]
    assert by["Demo Model A"]["compute_modes"] == ["resident", "attentionCache"] and by["Demo Model A"]["default_compute_mode"] == "attentionCache"
    assert by["Demo Model B"]["compute_modes"] == ["resident"] and not by["Demo Model B"]["cache_built"]


def test_full_job_is_persisted_with_media_and_metadata(stack):
    c, tmp = stack
    jid = submit(c, seed=7)
    j = wait_job(c, jid)
    assert j["status"] == "done", j.get("error")
    assert j["model_info"]["display"] == "Demo Model A" and j["params"]["compute_mode"] == "attentionCache" and j["params"]["fast_attention"] is True
    assert j["verified"] == "api" and j["seed"] == "7" and j["out_w"] and j["out_h"]       # lsof has no H3cApp process to inspect here
    v = c.get(f"/api/jobs/{jid}/video?download=1")
    assert v.status_code == 200 and b"ftyp" in v.content[:32] and "attachment" in v.headers["content-disposition"]
    assert c.get(f"/api/jobs/{jid}/thumb").status_code == 200
    assert c.get(f"/api/jobs/{jid}/preview", headers={**H, "Range": "bytes=0-99"}).status_code in (200, 206)
    assert list((tmp / "data/library").rglob("original.mp4"))


def test_switching_models_runs_in_fifo_order_and_never_uses_an_unbuilt_int8_cache(stack):
    c, _ = stack
    models = {m["display_name"]: m["id"] for m in c.get("/api/models").json()["models"]}
    assert c.post("/api/jobs", json=job(model_id=models["Demo Model B"], compute_mode="attentionCache")).status_code == 400   # B has no cache
    first = submit(c, model_id=models["Demo Model B"], compute_mode="resident")
    second = submit(c, model_id=models["Demo Model A"])
    j1, j2 = wait_job(c, first), wait_job(c, second)
    assert j1["status"] == j2["status"] == "done" and j1["finished_at"] <= j2["finished_at"]
    assert j1["model_info"]["display"] == "Demo Model B" and j2["model_info"]["display"] == "Demo Model A"
    assert [m["display_name"] for m in c.get("/api/models").json()["models"] if m["active"]] == ["Demo Model A"]


def test_cancel_and_security_basics(stack):
    c, _ = stack
    jid = submit(c)
    wait_job(c, jid, until=("running", "done"))
    c.post(f"/api/jobs/{jid}/cancel")
    assert wait_job(c, jid)["status"] in ("cancelled", "done")                  # either is legitimate if it raced to the end
    anon = httpx.Client(base_url=str(c.base_url), timeout=10)
    for path in ("/api/state", "/api/models", f"/api/jobs/{jid}/video"):
        assert anon.get(path).status_code == 401
    assert anon.post("/api/jobs", json=job()).status_code == 403                # no CSRF header
    assert c.post("/api/jobs", json=job(model_id="../../etc/passwd")).status_code == 400
    assert c.post("/api/jobs", json=job(first_frame="../../etc/passwd")).status_code == 400
