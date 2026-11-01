"""Standalone upscaler contract tests. No GPU, model or live H3cApp needed."""
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("H3STUDIO_DATA", tempfile.mkdtemp(prefix="h3-upscale-tests-"))
os.environ["H3STUDIO_SECURE_COOKIE"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402
from app import main, upscale  # noqa: E402

HEADERS = {"X-Requested-With": "h3studio"}


@pytest.fixture
def client(monkeypatch):
    # Small CI runners may have little disk. The rest of the test is all offline.
    monkeypatch.setattr(upscale.shutil, "disk_usage",
                        lambda path: SimpleNamespace(free=100 * 10**9))
    monkeypatch.setattr(upscale.subprocess, "run",
                        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=json.dumps(
                            {"streams": [{"width": 800, "height": 544}]})))
    c = TestClient(main.app)
    assert c.post("/api/login", json={"password": main.CFG["password"]},
                  headers=HEADERS).status_code == 200
    return c


def fake_video():
    # MP4-family magic; ffprobe's response is independently mocked.
    return io.BytesIO(b"\x00\x00\x00\x18ftypisom" + b"0" * 3000)


def upload(client):
    r = client.post("/api/upscale/upload",
                    files={"file": ("example.mp4", fake_video(), "video/mp4")},
                    headers=HEADERS)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["width"] == 800 and j["height"] == 544
    assert "extension" not in j and "path" not in j
    return j["id"]


def test_upscale_auth_and_csrf():
    anon = TestClient(main.app)
    assert anon.get("/api/upscale/jobs").status_code == 401
    assert anon.get("/api/upscale/methods").status_code == 401
    assert anon.post("/api/upscale/upload", files={"file": ("x.mp4", fake_video())},
                     headers=HEADERS).status_code == 401
    assert anon.post("/api/upscale/upload", files={"file": ("x.mp4", fake_video())}).status_code == 403


def test_upscale_invalid_media(client):
    for name, raw in [("bad.txt", fake_video()), ("fake.mp4", io.BytesIO(b"not a video"))]:
        r = client.post("/api/upscale/upload", files={"file": (name, raw)},
                        headers=HEADERS)
        assert r.status_code == 415, r.text


def test_upscale_validation_and_isolated_paths(client):
    jid = upload(client)
    assert client.get(f"/api/upscale/jobs/{jid}/source").status_code == 200
    assert client.get(f"/api/upscale/jobs/{jid}/enhanced").status_code == 404
    assert client.get("/api/upscale/jobs/invalid/source").status_code == 404
    assert client.get("/api/upscale/jobs/../../data/config.json").status_code in (404, 422)
    for body in ({"method": "evil", "scale": 2}, {"method": "realESRGANGeneral", "scale": 5},
                 {"method": "realESRGANGeneral", "scale": True}):
        r = client.post(f"/api/upscale/jobs/{jid}/start", json=body, headers=HEADERS)
        assert r.status_code == 400, r.text
    assert client.delete(f"/api/upscale/jobs/{jid}", headers=HEADERS).status_code == 200


def test_upscale_cannot_exceed_4096(client, monkeypatch):
    monkeypatch.setattr(upscale.subprocess, "run",
                        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=json.dumps(
                            {"streams": [{"width": 1500, "height": 900}]})))
    jid = upload_large(client)
    r = client.post(f"/api/upscale/jobs/{jid}/start",
                    json={"method": "realESRGANGeneral", "scale": 4}, headers=HEADERS)
    assert r.status_code == 400
    assert client.delete(f"/api/upscale/jobs/{jid}", headers=HEADERS).status_code == 200


def upload_large(client):
    r = client.post("/api/upscale/upload",
                    files={"file": ("large.mp4", fake_video(), "video/mp4")},
                    headers=HEADERS)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_upscale_mock_engine_completes(client, monkeypatch):
    from app import main as m
    calls = []

    def fake_h3(method, path, **kw):
        calls.append((method, path, kw))
        if path == "/api/upscale-file":
            params = kw["json"]
            assert params["upscaler"] == "realESRGANGeneral" and params["scale"] == 2
            assert params["path"] != params["output"]
            assert params["path"].startswith(str(m.DATA / "upscale"))
            Path(params["output"]).write_bytes(b"0" * 4096)
            return SimpleNamespace(status_code=202)
        if path == "/api/upscalers":
            return SimpleNamespace(status_code=200, json=lambda: {
                "upscalers": [{"id": "realESRGANGeneral", "available": True, "label": "General"}]})
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(m, "h3", fake_h3)
    monkeypatch.setattr(m, "h3_status", lambda: {"upscaling_video": False})
    methods = client.get("/api/upscale/methods").json()
    assert methods["methods"][0]["id"] == "realESRGANGeneral"

    jid = upload(client)
    r = client.post(f"/api/upscale/jobs/{jid}/start",
                    json={"method": "realESRGANGeneral", "scale": 2}, headers=HEADERS)
    assert r.status_code == 200, r.text
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        jobs = client.get("/api/upscale/jobs").json()["jobs"]
        current = next(j for j in jobs if j["id"] == jid)
        if current["status"] != "running":
            break
        time.sleep(.1)
    assert current["status"] == "done", current
    enhanced = client.get(f"/api/upscale/jobs/{jid}/enhanced?download=1")
    assert enhanced.status_code == 200 and enhanced.content == b"0" * 4096
    assert "attachment" in enhanced.headers["content-disposition"]
    assert len([c for c in calls if c[1] == "/api/upscale-file"]) == 1
    assert client.delete(f"/api/upscale/jobs/{jid}", headers=HEADERS).status_code == 200
