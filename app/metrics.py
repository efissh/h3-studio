"""Low-overhead, read-only Apple Silicon system metrics.

CPU is whole-system utilization averaged across logical cores, not the H3
process's CPU%. GPU comes from the Apple Silicon IOAccelerator registry.
RAM is psutil's available-memory-based usage, not Metal RSS and not macOS
memory-pressure free_level (which is kept separately as a scheduler guard).
Metrics are cached so multiple browsers do not repeatedly spawn ioreg.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time

import psutil

from .power import read_macmon

_GPU_RE = re.compile(r'"Device Utilization %"\s*=\s*(\d+)')
_GB = 1024 ** 3


def parse_gpu_utilization(output: str) -> int | None:
    """Return a reported percentage (or None); unsupported is NOT 0%."""
    m = _GPU_RE.search(output)
    if not m:
        return None
    percent = int(m.group(1))
    return percent if 0 <= percent <= 100 else None


class MetricsSampler:
    """At most one IORegistry sample per TTL, shared by all dashboard users."""

    def __init__(self, ttl: float = 3.0) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._sampled_monotonic = float("-inf")
        self._last: dict | None = None

    def _read_gpu(self) -> int | None:
        try:
            result = subprocess.run(
                ["/usr/sbin/ioreg", "-r", "-d", "1", "-c", "IOAccelerator"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if result.returncode != 0:
                return None
            return parse_gpu_utilization(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None

    def _collect(self) -> dict:
        cpu_pct = None
        memory_pct = memory_used_gb = memory_total_gb = memory_available_gb = None
        try:
            # Short explicit interval avoids misleading first-request 0% and
            # hours-long averaging after a tab has been closed.
            cpu_pct = round(min(100.0, max(0.0, psutil.cpu_percent(interval=0.1))), 1)
        except (OSError, RuntimeError, ValueError):
            pass
        try:
            vm = psutil.virtual_memory()
            memory_pct = round(float(vm.percent), 1)
            memory_total_gb = round(vm.total / _GB, 1)
            memory_available_gb = round(vm.available / _GB, 1)
            memory_used_gb = round((vm.total - vm.available) / _GB, 1)
        except (OSError, RuntimeError, ValueError):
            pass
        sensors = read_macmon()
        return {
            **sensors,
            "gpu_pct": self._read_gpu(),
            "cpu_pct": cpu_pct,
            "memory_pct": memory_pct,
            "memory_used_gb": memory_used_gb,
            "memory_total_gb": memory_total_gb,
            "memory_available_gb": memory_available_gb,
            "sampled_at": time.time(),
        }

    def read(self) -> dict:
        with self._lock:
            now = time.monotonic()
            if self._last is None or now - self._sampled_monotonic >= self.ttl:
                self._last = self._collect()
                self._sampled_monotonic = time.monotonic()
            return dict(self._last)
