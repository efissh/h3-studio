#!/usr/bin/env python3
"""Compare H3cApp compute modes on the ACTIVE model with identical inputs.

    python3 bench/compute_bench.py resident attentionCache resident attentionCache

Talks to H3cApp directly (127.0.0.1:8420); the web worker must be idle. Samples GPU utilisation
(ioreg), memory-free level, swap and H3cApp RSS once per second and writes bench/out/*.mp4 + results.json.
"""
import json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

H3 = os.environ.get("H3C_API_URL", "http://127.0.0.1:8420")
if not H3.startswith(("http://127.0.0.1", "http://localhost")):
    raise SystemExit("compute_bench talks to a local H3cApp only (loopback URL expected)")
TOKEN = Path(os.environ.get("H3C_TOKEN_FILE", Path(os.environ.get("H3C_SUPPORT_DIR", Path.home() / "Library/Application Support/H3cApp")) / "api-token"))
OUT = Path(__file__).resolve().parent / os.environ.get("BENCH_OUT", "out")
OUT.mkdir(exist_ok=True)
BODY = {"prompt": "A red fox walks through fresh snow in a pine forest, soft morning light, birds chirping.",
        "size_profile": "landscape-medium", "seconds": 5, "steps": 20, "speed_mode": "quality", "seed": 12345}


def call(method, path, body=None, raw=False):
    req = urllib.request.Request(H3 + path, method=method, headers={"Authorization": f"Bearer {TOKEN.read_text().strip()}"})
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310: H3 is validated to be a loopback http URL above
        data = r.read()
    return data if raw else json.loads(data)


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout


def sample():
    gpu = re.search(r'"Device Utilization %"=(\d+)', sh("ioreg", "-r", "-d", "1", "-c", "IOAccelerator"))
    swap = re.search(r"used = ([\d.]+)M", sh("sysctl", "-n", "vm.swapusage"))
    pid = sh("pgrep", "-x", "H3cApp").split()
    rss = int(sh("ps", "-o", "rss=", "-p", pid[0]).strip() or 0) / 1024 if pid else 0
    return {"gpu": int(gpu.group(1)) if gpu else None, "free": int(sh("sysctl", "-n", "kern.memorystatus_level")),
            "swap": float(swap.group(1)) if swap else None, "rss": rss}


def run(mode, tag):
    models = call("GET", "/api/models")
    active = [m["name"] for m in models if m["active"]]
    if call("GET", "/api/status")["is_generating"]:
        raise SystemExit("H3cApp is busy; run the benchmark when the queue is idle")
    base = sample()
    t0 = time.time()
    cm, _, extra = mode.partition("+")          # e.g. attentionCache+fast_attention (experimental, changes output)
    call("POST", "/api/generate", dict(BODY, compute_mode=cm, **({"fast_attention": True} if extra == "fast_attention" else {})))
    samples, denoise_start, seen = [], None, False
    while True:
        time.sleep(1)
        s = call("GET", "/api/status")
        samples.append((time.time() - t0, sample(), s.get("stage_title") or ""))
        if s["is_generating"]:
            seen = True
        elif seen or time.time() - t0 > 20:
            break
    wall = time.time() - t0
    st = call("GET", "/api/status")
    ok = st.get("result_available") and not str(st["engine_state"]).startswith("failed")
    path = OUT / f"{tag}.mp4"
    if ok:
        path.write_bytes(call("GET", "/api/result/video", raw=True))
    den = [x for x in samples if "enois" in x[2]]
    gpu_all = [x[1]["gpu"] for x in samples if x[1]["gpu"] is not None]
    gpu_den = [x[1]["gpu"] for x in den if x[1]["gpu"] is not None]
    res = {"tag": tag, "mode": mode, "active_model": active, "ok": bool(ok), "error": None if ok else st.get("engine_state"),
           "wall_s": round(wall, 1), "h3_elapsed_s": round(st.get("elapsed_seconds", 0), 1),
           "denoise_s": round(den[-1][0] - den[0][0], 1) if den else None,
           "gpu_avg_denoise": round(sum(gpu_den) / len(gpu_den), 1) if gpu_den else None,
           "gpu_peak": max(gpu_all) if gpu_all else None,
           "rss_peak_gb": round(max(x[1]["rss"] for x in samples) / 1024, 1),
           "free_level_min": min(x[1]["free"] for x in samples), "free_level_start": base["free"],
           "swap_mb_start": base["swap"], "swap_mb_max": max(x[1]["swap"] for x in samples),
           "bytes": path.stat().st_size if ok else None}
    print(json.dumps(res, ensure_ascii=False), flush=True)
    return res


if __name__ == "__main__":
    results = [run(m, f"{i + 1}_{m}") for i, m in enumerate(sys.argv[1:])]
    (OUT / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
