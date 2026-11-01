"""Offline video interpolation pipeline: 24fps H3 footage -> 48/60fps HQ Metal.

RifeMetal's stock CLI is a two-frame tool. Our small Swift worker keeps one
RifeInterpolator loaded throughout the job to avoid per-frame model reload.
Only local, server-selected paths reach the worker. Originals are never edited.
"""
from __future__ import annotations

import json
import math
import os
import selectors
import shutil
import subprocess
import time
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

TARGET_FPS = (48, 60)
MAX_SECONDS = 30
MAX_PIXELS = 1920 * 1080
MIN_FREE_BYTES = 5 * 1024**3

class Cancelled(RuntimeError):
    pass

def _run(command, *, cancel, timeout, error_log):
    with open(error_log, "ab") as err:
        child = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=err)
        end = time.monotonic() + timeout
        try:
            while child.poll() is None:
                if cancel():
                    raise Cancelled("Cancelled")
                if time.monotonic() > end:
                    raise TimeoutError("Video processing timed out")
                time.sleep(0.2)
            if child.returncode:
                raise RuntimeError("Video processing command failed (exit %s)" % child.returncode)
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()

def _probe(path, ffprobe):
    p = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30, check=True)
    streams = json.loads(p.stdout).get("streams", [])
    if not streams:
        raise ValueError("No video stream")
    s = streams[0]
    fps = Fraction(s["avg_frame_rate"])
    raw = Fraction(s["r_frame_rate"])
    if fps <= 0 or abs(float(fps - raw)) > 0.02:
        raise ValueError("Only constant-frame-rate video is supported")
    if int(s["width"]) * int(s["height"]) > MAX_PIXELS:
        raise ValueError("Maximum resolution is 1920x1080")
    return fps

def _plan(frame_count, source_rate, target_rate):
    """One output timestamp per target frame; exact Fraction avoids 24->60 drift."""
    if frame_count < 2 or source_rate >= target_rate:
        raise ValueError("Source needs at least two frames and an FPS below target")
    count = math.ceil(Fraction(frame_count * target_rate, 1) / source_rate)
    pairs = defaultdict(list)
    originals = {}
    for dest in range(count):
        pos = Fraction(dest, target_rate) * source_rate
        left = pos.numerator // pos.denominator
        frac = pos - left
        if left >= frame_count - 1:
            originals[dest] = frame_count - 1
        elif frac == 0:
            originals[dest] = left
        else:
            pairs[left].append((dest, float(frac)))
    return count, originals, pairs

def _link(source, dest):
    try:
        os.link(source, dest)
    except OSError:
        shutil.copyfile(source, dest)

def interpolate_video(source, destination, work, *, ffmpeg, ffprobe, worker,
                      target_fps=60, cancel=lambda: False, progress=lambda p: None):
    source, destination, work = Path(source), Path(destination), Path(work)
    if target_fps not in TARGET_FPS:
        raise ValueError("Target FPS must be 48 or 60")
    if not source.is_file() or not Path(worker).is_file():
        raise FileNotFoundError("Source or native RIFE worker unavailable")
    if shutil.disk_usage(work.parent).free < MIN_FREE_BYTES:
        raise RuntimeError("At least 5 GiB of temporary disk space required")
    fps = _probe(source, ffprobe)
    frames = work / "source"
    output = work / "frames"
    frames.mkdir(parents=True)
    output.mkdir(parents=True)
    errors = work / "ffmpeg-errors.log"
    progress(0.02)
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
          "-i", str(source), "-map", "0:v:0", "-vsync", "0",
          "-start_number", "0", str(frames / "%06d.png")],
         cancel=cancel, timeout=1200, error_log=errors)
    originals = sorted(frames.glob("*.png"))
    if not 2 <= len(originals) <= int(float(fps) * MAX_SECONDS) + 4:
        raise ValueError("Video length outside the 30-second safety limit")
    count, copies, pairs = _plan(len(originals), fps, target_fps)
    if count > target_fps * (MAX_SECONDS + 1):
        raise ValueError("Target video exceeds maximum supported duration")
    for dest, index in copies.items():
        _link(originals[index], output / ("%06d.png" % dest))
    progress(0.15)
    # Persistent Swift worker: one model initialization, one request per pair.
    # The worker is allowed to read/write only these private work paths.
    child = subprocess.Popen([str(worker)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, bufsize=1)
    try:
        poller = selectors.DefaultSelector()
        poller.register(child.stdout, selectors.EVENT_READ)
        for group, left in enumerate(sorted(pairs)):
            if cancel():
                raise Cancelled("Cancelled")
            members = pairs[left]
            payload = {"a": str(originals[left]), "b": str(originals[left + 1]),
                       "times": [t for _, t in members],
                       "outputs": [str(output / ("%06d.png" % i)) for i, _ in members]}
            child.stdin.write(json.dumps(payload) + "\n")
            child.stdin.flush()
            deadline = time.monotonic() + 180
            while True:
                if cancel():
                    raise Cancelled("Cancelled")
                if child.poll() is not None:
                    raise RuntimeError("RifeMetal worker exited unexpectedly")
                if time.monotonic() > deadline:
                    raise TimeoutError("RifeMetal frame group timed out")
                if poller.select(0.5):
                    response = json.loads(child.stdout.readline())
                    if not response.get("ok"):
                        raise RuntimeError(str(response.get("error", "RIFE failure"))[:240])
                    break
            progress(0.15 + 0.65 * (group + 1) / max(1, len(pairs)))
    finally:
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=4)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    if len(list(output.glob("*.png"))) != count:
        raise RuntimeError("Incomplete interpolated frame sequence")
    progress(0.82)
    silent = work / "silent.mp4"
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
          "-framerate", str(target_fps), "-start_number", "0",
          "-i", str(output / "%06d.png"), "-frames:v", str(count),
          "-c:v", "h264_videotoolbox", "-b:v", "12M",
          "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(silent)],
         cancel=cancel, timeout=1200, error_log=errors)
    progress(0.92)
    partial = work / "final.mp4"
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
          "-i", str(silent), "-i", str(source),
          "-map", "0:v:0", "-map", "1:a?", "-c", "copy",
          "-shortest", "-movflags", "+faststart", str(partial)],
         cancel=cancel, timeout=300, error_log=errors)
    if not partial.is_file() or partial.stat().st_size < 1024:
        raise RuntimeError("RIFE output not produced")
    if cancel():
        raise Cancelled("Cancelled")
    # Committed only when all frames and the final MP4 are complete.
    os.replace(partial, destination)
    progress(1.0)
    return {"fps": target_fps, "frames": count, "source_frames": len(originals),
            "engine": "RifeMetal v0.1.8 HQ"}
