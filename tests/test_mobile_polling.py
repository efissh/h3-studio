"""Regression tests for low-bandwidth H3 state polling (no network/GPU needed)."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("H3STUDIO_DATA", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main  # noqa: E402


def _job(index):
    return {
        "id": f"{index+1:032x}",
        "status": "done",
        "created_at": 100.0 + index,
        "finished_at": 120.0 + index,
        "started_at": 110.0 + index,
        "model_id": "sakura-q8",
        "params": json.dumps({
            "size_profile": "portrait-medium", "seconds": 5, "steps": 20,
            "speed_mode": "quality", "compute_mode": "attentionCache",
            "fast_attention": True, "prompt": "large" * 900,
        }),
        "prompt": "Long real user prompt " * 200,
        "model_info": json.dumps({
            "display": "H3 Sakura", "quantization": "Q8",
            "h3capp_version": "0.7.3", "debug_heavy": "x" * 900,
        }),
        "video_path": "/private/video.mp4",
        "thumb_path": "/private/thumbnail.jpg",
        "preview_path": "/private/preview.mp4",
        "gen_seconds": 33.0, "progress": 1, "eta": 0, "stage": "done",
        "seed": "45", "ab_group": None, "error": None, "note": None,
    }


def test_state_polling_is_small_and_history_is_lazy(monkeypatch):
    records = list(reversed([_job(i) for i in range(72)]))
    calls = []

    def fake_q(sql, args=()):
        calls.append((sql, args))
        if "COUNT(*) AS n" in sql:
            return [{"n": len(records), "created": 171.0, "finished": 191.0}]
        if "status IN ('queued','running')" in sql:
            return []
        if "ORDER BY created_at DESC LIMIT ? OFFSET ?" in sql:
            limit, offset = args
            return records[offset:offset + limit]
        if "ORDER BY created_at DESC LIMIT 200" in sql:
            return records
        if "WHERE id=?" in sql:
            return records[:1]
        return []  # A background worker may query its own queue while this test runs.

    monkeypatch.setattr(main, "q", fake_q)
    monkeypatch.setattr(main, "h3_status", lambda: {"engine_state": "ready"})
    monkeypatch.setattr(main.METRICS, "read", lambda: {"gpu_pct": 3.0})
    monkeypatch.setattr(main, "free_disk_gb", lambda: 28.5)
    monkeypatch.setattr(main, "free_mem_pct", lambda: 90.0)
    with TestClient(main.app) as cli:
        hdr = {"X-Requested-With": "h3studio"}
        assert cli.post("/api/login", headers=hdr,
                        json={"password": main.CFG["password"]}).status_code == 200
        live = cli.get("/api/state?compact=1")
        assert live.status_code == 200
        data = live.json()
        assert data["recent"] == []
        assert data["active"] == []
        assert data["history_revision"]
        assert "system" in data and "h3" in data
        assert len(live.content) < 5000
        assert all("LIMIT 200" not in sql for sql, _ in calls)

        first = cli.get("/api/jobs/history?limit=20")
        next_page = cli.get("/api/jobs/history?limit=20&offset=20")
        assert first.status_code == 200 and next_page.status_code == 200
        assert len(first.json()["jobs"]) == 20
        assert first.json()["jobs"][-1]["id"] != next_page.json()["jobs"][0]["id"]
        assert first.json()["jobs"][0]["prompt"] == records[0]["prompt"][:180]
        assert "debug_heavy" not in json.dumps(first.json())
        assert "/private/video.mp4" not in json.dumps(first.json())
        assert "large" * 900 not in json.dumps(first.json())
        assert len(first.content) < 22000

        detail = cli.get("/api/jobs/" + records[0]["id"])
        assert detail.status_code == 200
        assert detail.json()["prompt"] == records[0]["prompt"]
        assert detail.json()["params"]["prompt"] == "large" * 900
        assert "video_path" not in detail.json()
        assert cli.get("/api/jobs/history?limit=201").status_code == 400
        assert cli.get("/api/jobs/history?limit=0").status_code == 400
        assert cli.get("/api/jobs/history?offset=-1").status_code == 400
        assert cli.get("/api/jobs/../../etc/passwd").status_code in (404, 405)

    anonymous = TestClient(main.app)
    for route in ("/api/state?compact=1", "/api/jobs/history",
                  "/api/jobs/" + records[0]["id"]):
        assert anonymous.get(route).status_code == 401


def test_frontend_has_no_overlapping_live_poll():
    s = (Path(__file__).resolve().parents[1] / "static/index.html").read_text()
    assert "stateInFlight" in s
    assert "/api/state?compact=1" in s
    assert "/api/jobs/history?limit=" in s
    assert "document.addEventListener('visibilitychange'" in s
    assert "scheduleState(" in s
    assert "setInterval(refresh,2000)" not in s
    assert "async function openJob(id)" in s
    assert "/api/jobs/'+id" in s
    assert "loadMoreHistory" in s
    assert "loadRifeSources()" in s
