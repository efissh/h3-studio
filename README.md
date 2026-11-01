# H3 Studio

A small, self-hosted web workbench for **MiniMax H3 video generation on Apple Silicon Macs**. It sits in front of
[H3cApp](https://github.com/JunzoKamahara/H3cApp) (the engine that does the actual rendering on your Mac's GPU) and adds what a
browser can do better than a desktop window: a reliable job queue, a persistent video library, model switching with proof of which
model really ran, hardware telemetry, and installable PWA access from your phone or another computer.

* **Local by default.** It listens on `127.0.0.1` only. Remote access (for example over [Tailscale](https://tailscale.com)) is optional and off.
* **Your data stays on your Mac.** Prompts, uploads, videos and the SQLite database live in `data/`; nothing is sent anywhere.
* **Open and editable.** Plain Python (FastAPI) plus one HTML file with vanilla JavaScript. No build step, no npm, no CDN. It is meant
  to be forked and reshaped with an AI coding assistant such as Claude Code (see [`CLAUDE.md`](CLAUDE.md)).
* **Not included:** H3cApp and the model weights. You install those yourself and accept their licenses ([`docs/LICENSES.md`](docs/LICENSES.md)).

> **Interface language:** the web UI is currently **Chinese only** (messages from the server are Chinese too). The code, docs and
> API are English. Translating is a mechanical job: see [`docs/LOCALIZATION.md`](docs/LOCALIZATION.md).


## Features

| | |
|---|---|
| **Generate** | text-to-video, first-frame and first+last-frame image-to-video; duration, size, steps, seed, quality/fast modes, M5 Fast attention toggle |\n| **AI video upscale** | New independent tab: upload ordinary MP4/MOV/M4V, use H3cApp's bundled Real-ESRGAN General/Anime or MetalFX, select 1.5×–4×, view progress and download the output separately |
| **Queue** | strict FIFO, one H3 job at a time, progress/ETA, cancel, retry; survives restarts (a running job is re-adopted or marked failed, never falsely "done") |
| **Library** | every result is saved *before* the next job starts: original MP4, thumbnail, browser-friendly H.264 preview, prompt, seed and all parameters; download and "generate again" |
| **Models** | every model registered in H3cApp is listed automatically. Each job records which model ran; the app **verifies** the switch (API + the files the engine really has open). It never silently falls back to another model |
| **Compute modes** | Resident, Fast INT8 cache (M5-class GPUs, once the cache is built in H3cApp) and optional SSD streaming; only modes that are really available are offered |
| **A/B compare** | the same prompt and seed on several models, queued back to back |
| **Telemetry** | GPU, CPU, RAM; optional temperatures and power via [macmon](https://github.com/vladkens/macmon) (unreadable values show "—", never invented numbers) |
| **Guards** | refuses new jobs when disk is low, delays starts under memory pressure |
| **PWA** | installable from Chrome/Edge/Safari; foldable and phone layouts; dark/light themes; "desktop site mode" detection |
| **Security** | password login, CSRF header + Origin check, login rate limit, upload type/size checks by magic bytes, no path ever comes from the browser |

## Requirements

* An **Apple Silicon Mac** (M1 or newer; the Fast INT8 cache needs an **M5-class** GPU), macOS 15 or newer, as required by H3cApp.
* [H3cApp](https://github.com/JunzoKamahara/H3cApp/releases) with at least one MiniMax H3 model registered in it. Plan for tens to hundreds of GB of disk: see H3cApp's docs.
* Python **3.10+** (`brew install python@3.12`; macOS's built-in 3.9 is too old for the security-patched dependencies) and `ffmpeg` (`brew install ffmpeg`).
* Optional: `macmon` (telemetry), `tailscale` (remote access).

Developed and tested on an M5 Ultra with 96 GB. Other Apple Silicon Macs (for example an M5 Max with 128 GB) are expected to work wherever H3cApp does, but have not been tested by the author. `bin/h3studio doctor` tells you what it detects.

## Quick start

```bash
git clone https://github.com/efissh/h3-studio.git
cd h3-studio
./install.sh            # venv + dependencies + first-run setup; prints your password once
bin/h3studio start      # then open http://127.0.0.1:8195
```

No GPU or model yet? Try the interface against a **mock engine** (it produces test-pattern videos, not model output):

```bash
bin/h3studio demo
```

Full instructions and troubleshooting: [`docs/INSTALL.md`](docs/INSTALL.md), [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

## How it works

```
browser ──HTTP──▶ H3 Studio (FastAPI, 127.0.0.1:8195) ──HTTP + bearer token──▶ H3cApp (127.0.0.1:8420) ──▶ Metal GPU
                      │   one FIFO worker, SQLite queue, model verification
                      └── data/ (config, jobs.sqlite, uploads, library/<date>/<job>/{original,preview}.mp4, thumb.jpg)
```

The browser never talks to H3cApp. H3 Studio reads H3cApp's API token from its own file on every request and never sends it to the browser or the logs.

## Everyday commands

`bin/h3studio start | stop | restart | status | logs | doctor | password | rotate-password | run | demo | update`
and the optional `launchagent-install` (start at login) and `tailscale-on` / `tailscale-off`. `bin/h3studio help` lists everything.

## Security in one paragraph

Single-user tool: one shared password, no accounts. It binds to loopback; it refuses other addresses unless you explicitly allow it. Do not
put it on the public internet and never use Tailscale *Funnel*. Read [`docs/SECURITY-MODEL.md`](docs/SECURITY-MODEL.md) before enabling any remote access, and report problems as described in [`SECURITY.md`](SECURITY.md).

## Documentation

[Install](docs/INSTALL.md) · [AI video upscale](docs/VIDEO-UPSCALE.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) · [Models and compute modes](docs/MODELS.md) · [INT8 cache](docs/INT8_CACHE.md) ·
[Remote access (optional)](docs/REMOTE-ACCESS.md) · [Security model](docs/SECURITY-MODEL.md) · [Developer guide](docs/DEVELOPER.md) ·
[Localization](docs/LOCALIZATION.md) · [Foldable layout](docs/FOLDABLE.md) · [Licenses](docs/LICENSES.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

## Responsible use

Generated videos should be disclosed as AI-generated when published, and the model's territory and acceptable-use rules apply to you, not to this software.
See [`docs/LICENSES.md`](docs/LICENSES.md).

## License

MIT for the code in this repository ([`LICENSE`](LICENSE)). H3cApp, the models, ffmpeg and other programs keep their own licenses.
