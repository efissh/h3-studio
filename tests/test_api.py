"""Offline tests: auth, CSRF, validation, upload hardening. No H3cApp needed."""
import io, os, sys, tempfile
from pathlib import Path

os.environ["H3STUDIO_DATA"] = tempfile.mkdtemp()
os.environ["H3STUDIO_SECURE_COOKIE"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402

H = {"X-Requested-With": "h3studio"}
c = TestClient(main.app)


def login():
    r = c.post("/api/login", json={"password": main.CFG["password"]}, headers=H)
    assert r.status_code == 200


def test_requires_login():
    assert TestClient(main.app).get("/api/state").status_code == 401


def test_csrf_and_origin():
    assert c.post("/api/login", json={}).status_code == 403
    r = c.post("/api/login", json={}, headers={**H, "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_wrong_password():
    assert c.post("/api/login", json={"password": "nope"}, headers=H).status_code == 401


def test_validation_and_traversal():
    login()
    assert c.post("/api/jobs", json={"prompt": "x", "steps": 99}, headers=H).status_code == 400
    assert c.post("/api/jobs", json={"prompt": ""}, headers=H).status_code == 400
    bad = {"prompt": "x", "first_frame": "../../etc/passwd"}
    assert c.post("/api/jobs", json=bad, headers=H).status_code == 400


def test_upload_magic_bytes():
    login()
    r = c.post("/api/upload", files={"file": ("a.png", io.BytesIO(b"not an image"))}, headers=H)
    assert r.status_code == 415
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    r = c.post("/api/upload", files={"file": ("a.png", io.BytesIO(png))}, headers=H)
    assert r.status_code == 200 and r.json()["id"].endswith(".png")


def test_clean_params_maps_to_h3_body():
    p = main.clean_params({"prompt": "hi", "shape": "portrait", "size": "small", "seconds": 3, "steps": 10, "seed": "7"})
    body = main.h3_body(p, 7)
    assert body["size_profile"] == "portrait-small" and body["seed"] == 7 and "token" not in str(body).lower()
    assert p["fast_attention"] is True and body["fast_attention"] is True  # new jobs default ON
    off = main.clean_params({"prompt": "hi", "fast_attention": False})
    assert off["fast_attention"] is False
    assert main.h3_body(off, 7)["fast_attention"] is False  # per-job OFF
    import pytest
    for bad in ("false", 0, 1, None, {}):
        with pytest.raises(Exception) as e:
            main.clean_params({"prompt": "hi", "fast_attention": bad})
        assert e.value.status_code == 400


def test_legacy_job_does_not_acquire_new_fast_mode_on_retry():
    legacy = {
        "prompt": "hi", "size_profile": "landscape-medium", "seconds": 5,
        "steps": 20, "speed_mode": "quality", "compute_mode": "resident",
    }
    assert main.h3_body(legacy, 1)["fast_attention"] is False


def test_model_endpoints_reject_bad_ids(monkeypatch):
    login()
    assert c.post("/api/jobs", json={"prompt": "x", "model_id": "/etc/passwd"}, headers=H).status_code == 400
    assert c.post("/api/jobs/ab", json={"prompt": "x", "model_ids": ["sakura-q8"]}, headers=H).status_code == 400


def test_new_job_defaults_to_int8_and_fast_with_independent_opt_out(monkeypatch):
    login()
    captured = []
    monkeypatch.setattr(main, "pick_model", lambda _: "sakura-q8")
    monkeypatch.setattr(main, "pick_mode", lambda mid, mode: mode or "attentionCache")
    monkeypatch.setattr(main, "insert_job", lambda params, seed, **kw: captured.append(dict(params)) or "fake-job")
    r = c.post("/api/jobs", json={"prompt": "test"}, headers=H)
    assert r.status_code == 200
    assert captured[-1]["compute_mode"] == "attentionCache"
    assert captured[-1]["fast_attention"] is True
    assert main.h3_body(captured[-1], 7)["fast_attention"] is True

    r = c.post("/api/jobs", json={"prompt": "test", "compute_mode": "resident",
                                   "fast_attention": False}, headers=H)
    assert r.status_code == 200
    assert captured[-1]["compute_mode"] == "resident"
    assert captured[-1]["fast_attention"] is False


def test_session_cookie_flags_and_lockout():
    fresh = TestClient(main.app)
    r = fresh.post("/api/login", json={"password": main.CFG["password"]}, headers=H)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=" in cookie        # JS can't read it, no cross-site sends
    attacker = TestClient(main.app)
    main._fails.clear()
    codes = [attacker.post("/api/login", json={"password": f"wrong{i}"}, headers=H).status_code for i in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]                                    # locked after 5 failures
    assert attacker.post("/api/login", json={"password": main.CFG["password"]}, headers=H).status_code == 429
    main._fails.clear()


def test_public_surface_is_exactly_the_documented_one():
    anon = TestClient(main.app)
    open_get = {"/", "/manifest.webmanifest", "/pwa/icon-192.png", "/pwa/icon-512.png", "/pwa/icon-180.png", "/api/session"}
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if getattr(route, "methods", None) and "GET" in route.methods and "{" not in path and path not in open_get:
            assert anon.get(path).status_code == 401, path
    for path in open_get:
        assert anon.get(path).status_code == 200, path


def test_media_ids_cannot_escape_the_library():
    login()
    for evil in ("../../etc/passwd", "..%2f..%2fetc%2fpasswd", "x' OR '1'='1", "%00"):
        for suffix in ("video", "preview", "thumb"):
            assert c.get(f"/api/jobs/{evil}/{suffix}").status_code in (404, 422)
    for evil in ("../../etc/passwd", "x.png/../../secret", "..%2fconfig.json"):
        assert c.get(f"/api/upload/{evil}").status_code == 404
