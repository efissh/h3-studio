"""macmon is optional: temperatures/power must remain safe when unavailable."""
from __future__ import annotations

import json
from unittest.mock import patch

from app.power import MAX_BYTES, MACMON_JSON, parse_power, read_macmon


def test_macmon_valid_sensor_snapshot():
    example = {
        "soc": {"vm": False},
        "temp": {"cpu_temp_avg": 53.267, "gpu_temp_avg": 45.731},
        "cpu_power": 24.32, "gpu_power": 65.79,
        "ane_power": 0.0, "sys_power": 118.76,
    }
    m = parse_power(example)
    assert m["cpu_temp_c"] == 53.3
    assert m["gpu_temp_c"] == 45.7
    assert m["cpu_power_w"] == 24.3
    assert m["gpu_power_w"] == 65.8
    assert m["system_power_w"] == 118.8
    assert m["ane_power_w"] == 0.0
    assert "非插座功耗" in m["power_scope"]


def test_missing_or_unsupported_sensor_does_not_fake_zero():
    assert parse_power(None)["cpu_temp_c"] is None
    assert parse_power({})["system_power_w"] is None
    m = parse_power({"temp": {"cpu_temp_avg": 0, "gpu_temp_avg": 999},
                     "cpu_power": 0, "gpu_power": 0, "sys_power": 0, "ane_power": 0})
    assert m["cpu_temp_c"] is None
    assert m["gpu_temp_c"] is None
    assert m["gpu_power_w"] is None
    assert m["system_power_w"] is None
    assert m["ane_power_w"] is None


def test_unexpected_types_and_vm_do_not_create_bogus_values():
    m = parse_power({"soc": {"vm": True}, "cpu_power": 58, "temp": {"gpu_temp_avg": 40}})
    assert m["cpu_power_w"] is None
    assert m["gpu_temp_c"] is None
    m = parse_power({"temp": {"cpu_temp_avg": "54"}, "sys_power": "100"})
    assert m["cpu_temp_c"] is None
    assert m["system_power_w"] is None
    m = parse_power({"cpu_power": True, "gpu_power": float("nan")})
    assert m["cpu_power_w"] is None
    assert m["gpu_power_w"] is None


def test_http_endpoint_is_fixed_localhost(monkeypatch):
    import app.power as power
    urls = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def read(self, n):
            assert n == MAX_BYTES + 1
            return json.dumps({"temp": {"cpu_temp_avg": 63}, "gpu_power": 83.12}).encode()

    def request(req, timeout):
        assert timeout <= 1
        urls.append(req.full_url)
        return Response()

    monkeypatch.setattr(power.urllib.request, "urlopen", request)
    m = read_macmon()
    assert urls == [MACMON_JSON]
    assert m["gpu_power_w"] == 83.1
    assert m["cpu_temp_c"] == 63.0


def test_network_failure_degrades_gracefully(monkeypatch):
    import app.power as power

    def bad(*_, **__):
        raise OSError("not installed")

    monkeypatch.setattr(power.urllib.request, "urlopen", bad)
    m = read_macmon()
    assert m["cpu_temp_c"] is None
    assert m["system_power_w"] is None
