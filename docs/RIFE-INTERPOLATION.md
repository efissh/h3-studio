# RIFE Metal interpolation (optional, online-only H3 Studio postprocessor)

## What this does
From the **AI 插帧** tab choose a completed H3 Studio video and start a new,
separate output job. Default: **HQ full-resolution RIFE inference → 60fps**;
48fps is also supported. The original stays untouched, and the original audio
tracks are copied unchanged into a separate, downloadable MP4. No H3 video
generation or INT8 cache rebuilding is required.

Implementation:
- \`app/rife_video.py\`: FPS planning (exact rational timestamps), source
  frame extraction, one persistent Metal worker, VideoToolbox H.264 encoding,
  optional audio remux, atomic output, temporary-frame cleanup and cancellation.
- \`tools/rife_stream/\`: a small SwiftPM executable that keeps **one RifeMetal
  instance loaded per job** and interpolates successive frame pairs in HQ.
- \`app/interpolation.py\`: authenticated routes, one persistent job queue,
  GPU-busy checks, independent private storage and upstream version reminders.
- The app intentionally has **no automatic post-generation processing**; each
  interpolation must be requested explicitly from a completed H3 result.

## Version provenance and upgrades

The Swift dependency is intentionally pinned to RifeMetal **0.1.8**. Its
tagged Package.swift and RifeConfiguration source identify the **v4.25**
bundled weights. Some upstream README text refers to v4.26, but do not
advertise a model-version upgrade until the released sources are inspected.
This repository ships **no copied weights** and does not silently download
or execute model files when the server runs.

After authenticated login, the app checks the **fixed official GitHub
Releases API** at most once per 24 hours per server process. A newer semantic
version produces an **upgrade reminder** and links to official release notes.
An unavailable GitHub connection is harmless and shows no update claim.

**No automatic upgrade.** Review source, third-party license changes,
compatibility and performance first. Then update the exact version in
\`tools/rife_stream/Package.swift\`, rebuild the Swift worker, run regression
tests and one small offline job, and only then deploy. Keep the previous
binary and Git commit for rollback. A Homebrew \`brew upgrade\` is NOT how
this pinned Swift worker is updated.

RifeMetal is Apache-2.0 and the underlying Practical-RIFE weights are MIT
(see its upstream THIRD-PARTY.md). The H3 Studio public repository does not
redistribute those weights; SwiftPM fetches the pinned dependency at build.

## Installation on the Mac that runs H3 Studio

1. Confirm Xcode toolchain / Swift 5.10+, ffmpeg and ffprobe. No CUDA needed.
2. From the H3 Studio repository root, run:

       cd tools/rife_stream
       swift build -c release
       ls -lh .build/release/h3-rife-stream
       cd ../..

   This is an optional build. Existing H3 Studio functions work without it;
   the interpolation tab then shows *not installed*.
3. In the H3 Studio Python environment, run:

       python -m pytest -q tests/test_rife_interpolation.py

4. Use a **copy** of an existing short, completed H3 video and verify the
   new job at 60fps, exact play duration (within one frame), audio stream,
   no motion artifacts on an obvious cut, and preserved original MP4.
5. Check queuing while the H3 GPU is busy. Do not run RIFE and H3 generation
   concurrently on the production Mac. Restart **only the H3 Studio web
   service**, when idle. Do not restart H3cApp, oMLX, Open WebUI or macmon.

## Routes (all authenticated)
- GET \`/api/interpolate/status\`: installed, pinned version, HQ, upgrade hint
- GET \`/api/interpolate/jobs\`: private job progress/history
- POST \`/api/interpolate/from-job\`: \`{"job_id":"<done job id>","fps":60}\`
- POST \`/api/interpolate/jobs/<id>/cancel\`
- GET \`/api/interpolate/jobs/<id>/video?download=1\`

No public model or video endpoints. The browser cannot submit source file
paths, and no upstream response URL is interpolated into executable code.
There is **no installation or upgrade action endpoint**.

## Limits and follow-up optimization

Current scope: completed, constant-frame-rate H3 MP4 videos with at least
two frames, under 30 seconds and at most 1920x1080. 48 and 60fps only.
A minimum of 5 GiB of temporary free storage is required, plus the server's
configured reserve. All intermediate PNGs are deleted when the job completes
or fails. No HDR, variable-FPS source, scene-cut processing or general user
video upload is included in this first version.

Although Metal model initialization is reused, PNG extraction and encoding
still incur disk/CPU overhead. Benchmark on the target M5 Ultra rather than
claiming a 5-second video will finish in a few seconds. For very long clips,
future work should implement an AVFoundation pixel-buffer streaming pipeline
and scene-cut handling; do not promise these exist already.

Rollback: revert the PR, restart Web Studio only. Original H3 job records,
output MP4s, model registration and INT8 caches remain unchanged.
