"""Read-only telemetry tests; no H3cApp or Apple GPU is needed."""
from __future__ import annotations

from types import SimpleNamespace

from app.metrics import MetricsSampler, parse_gpu_utilization


def test_gpu_ioreg_parser():
    assert parse_gpu_utilization('"Device Utilization %"=100') == 100
    assert parse_gpu_utilization('{"Device Utilization %" = 0}') == 0
    assert parse_gpu_utilization('"Device Utilization %"=67') == 67
    assert parse_gpu_utilization('"Device Utilization %"=101') is None
    assert parse_gpu_utilization('"Renderer Utilization %"=95') is None
    assert parse_gpu_utilization("") is None


def test_sample_metrics_and_tolerate_missing_gpu(monkeypatch):
    import app.metrics as metrics

    monkeypatch.setattr(metrics.psutil, "cpu_percent", lambda **k: 31.25)
    monkeypatch.setattr(
        metrics.psutil, "virtual_memory",
        lambda: SimpleNamespace(total=96 * 1024**3, available=64 * 1024**3, percent=33.3),
    )
    monkeypatch.setattr(MetricsSampler, "_read_gpu", lambda _: None)
    m = MetricsSampler(ttl=3).read()
    assert m["gpu_pct"] is None
    assert m["cpu_pct"] == 31.2 or m["cpu_pct"] == 31.3
    assert m["memory_pct"] == 33.3
    assert m["memory_used_gb"] == 32.0
    assert m["memory_available_gb"] == 64.0
    assert m["memory_total_gb"] == 96.0
    assert m["sampled_at"] > 0


def test_ttl_reuses_snapshot_for_multiple_browser_requests(monkeypatch):
    calls = []

    def collect(_):
        calls.append(1)
        return {"gpu_pct": 80, "sampled_at": 1}

    monkeypatch.setattr(MetricsSampler, "_collect", collect)
    sampler = MetricsSampler(ttl=60)
    assert sampler.read()["gpu_pct"] == 80
    assert sampler.read()["gpu_pct"] == 80
    assert len(calls) == 1
    sampler.read()["gpu_pct"] = 0
    assert sampler.read()["gpu_pct"] == 80  # caller cannot mutate cache


def test_ioreg_failure_is_unknown_not_idle(monkeypatch):
    import app.metrics as metrics

    def fail(*_, **__):
        raise metrics.subprocess.TimeoutExpired(cmd="ioreg", timeout=2)

    monkeypatch.setattr(metrics.subprocess, "run", fail)
    assert MetricsSampler()._read_gpu() is None


def test_authenticated_state_includes_system_metrics(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    monkeypatch.setattr(main.METRICS, "read", lambda: {
        "gpu_pct": 78, "cpu_pct": 23, "memory_pct": 52,
        "memory_total_gb": 96, "memory_used_gb": 49.9,
        "memory_available_gb": 46.1, "sampled_at": 123.0,
    })
    monkeypatch.setattr(main, "h3_status", lambda: {"engine_state": "ready"})
    with TestClient(main.app) as client:
        assert client.get("/api/state").status_code == 401
        login = client.post("/api/login", json={"password": main.CFG["password"]},
                            headers={"X-Requested-With": "h3studio"})
        assert login.status_code == 200
        response = client.get("/api/state")
        assert response.status_code == 200
        payload = response.json()
        assert payload["system"]["metrics"]["gpu_pct"] == 78
        assert "free_mem_pct" in payload["system"]  # existing guard stays
        assert "active" in payload and "recent" in payload
