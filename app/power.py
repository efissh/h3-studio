"""Optional, unprivileged macmon adapter for Apple Silicon thermal/power data.

Source: vladkens/macmon `serve --host 127.0.0.1 --port 9197`
Only reads a fixed loopback endpoint. No sudo, command execution, service
installation, external URL, or trust in browser-supplied paths.
`sys_power` is a sensor-derived system estimate, NOT AC wall power.
Unsupported/invalid sensor readings are represented as None, not fake 0.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from typing import Any

MACMON_JSON = "http://127.0.0.1:9197/json"
MAX_BYTES = 256_000


def _number(value: Any, lower: float, upper: float, *, allow_zero: bool = True) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if not math.isfinite(v) or v < lower or v > upper or (not allow_zero and v == 0):
        return None
    return round(v, 1)


def parse_power(data: Any) -> dict:
    """Return bounded, unit-labelled values; never infer missing fields."""
    result = {
        "cpu_temp_c": None, "gpu_temp_c": None,
        "cpu_power_w": None, "gpu_power_w": None,
        "ane_power_w": None, "system_power_w": None,
        "power_scope": "macmon sys_power: 传感器估算，非插座功耗",
    }
    if not isinstance(data, dict):
        return result
    soc = data.get("soc")
    if isinstance(soc, dict) and soc.get("vm") is True:
        return result
    t = data.get("temp")
    if isinstance(t, dict):
        result["cpu_temp_c"] = _number(t.get("cpu_temp_avg"), 0, 125, allow_zero=False)
        result["gpu_temp_c"] = _number(t.get("gpu_temp_avg"), 0, 125, allow_zero=False)
    # macOS 27 and newer SoCs can expose uninitialised 0 power counters.
    # A reported 0 for CPU/GPU/system power is ambiguous; treat it as unknown.
    for dst, src in (
        ("cpu_power_w", "cpu_power"),
        ("gpu_power_w", "gpu_power"),
        ("ane_power_w", "ane_power"),
        ("system_power_w", "sys_power"),
    ):
        result[dst] = _number(data.get(src), 0, 1000, allow_zero=(dst == "ane_power_w"))
    # An out-of-sync or entirely unsupported CLPC counter set may look like zero.
    if all(result[k] is None for k in ("cpu_power_w", "gpu_power_w", "system_power_w")):
        result["ane_power_w"] = None
    return result


def read_macmon() -> dict:
    try:
        req = urllib.request.Request(MACMON_JSON, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=0.8) as response:  # nosec B310: fixed http://127.0.0.1 URL
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("macmon payload too large")
        return parse_power(json.loads(raw))
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError, urllib.error.URLError):
        return parse_power(None)
