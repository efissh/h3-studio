# Developer guide

## Layout
```
app/main.py         FastAPI app: auth, upload, job API, FIFO worker + monitor, persistence, media, metrics endpoint
app/models.py       ModelManager: discovery, ids, switching + verification, compute modes
app/config.py       data/config.json (create, defaults, secrets rotation); shared with the CLI
app/migrations.py   reversible SQLite migrations (PRAGMA user_version) with automatic backups
app/metrics.py      GPU/CPU/RAM sampler (ioreg, psutil), cached;  app/power.py  optional macmon reader (loopback only)
app/doctor.py       read-only environment diagnostics
static/index.html   the whole UI (HTML + CSS + vanilla JS), manifest and icons
bin/h3studio        CLI;  install.sh  installer;  deploy/  LaunchAgent templates
tools/              mock_h3capp.py (fake engine), audit_public.py, make_icons.py, fetch_hf_manifest.py, gguf_index.py
tests/              pytest suite (offline); bench/  optional benchmarking helpers
```

## Run from a checkout
```bash
./install.sh --dev
bin/h3studio run            # foreground, auto-reload, http://127.0.0.1:8195
bin/h3studio demo           # same UI against the mock engine (no H3cApp/GPU/model)
.venv/bin/python -m pytest -q
python3 tools/audit_public.py
```
Optional: install Node.js to also execute the two JavaScript tests that are skipped otherwise.

## How a job flows
1. `POST /api/jobs` → `clean_params()` validates everything, `pick_model()`/`pick_mode()` check the model id and compute mode against `ModelManager`, the row is inserted `queued`.
2. The worker thread takes the oldest queued job when: disk and memory guards pass, H3cApp is `ready` and idle. It calls `ensure_active(model)` (select + verify), validates the mode again, then `POST /api/generate`.
3. `monitor()` polls `GET /api/status` every 2 s, mirrors progress/stage into the row, runs `verify_loaded()` once, handles cancel, and on completion downloads the result **into `data/library` (atomic rename)** *before* marking the job done. Only then can the next job start.
4. Thumbnail and H.264 preview are made with ffmpeg; failures there never fail the job.
5. On restart a `running` job is re-adopted if H3cApp is still generating, otherwise marked failed (retryable). It is never marked done without a saved file.

## Talking to H3cApp
Everything goes through `h3()` in `main.py` / the `call` passed to `ModelManager`. Endpoints used: `GET /api/status`, `POST /api/generate`, `POST /api/cancel`,
`GET /api/result/video`, `GET /api/models`, and the undocumented `POST /api/models/select`, `GET /api/models/detail`. If a future H3cApp changes them, adapt `models.py` (`_detail` parses
the detail rows by title) and update `tools/mock_h3capp.py` plus `tests/test_models.py`; the e2e tests then show whether the whole flow still works.

## Database changes
Add a step to `MIGRATIONS` in `app/migrations.py` with both `up` and `down` statements and a test in `tests/test_models.py` (see the existing up/down round-trip). The app migrates on start and writes a backup first (`data/backups/`).
CLI: `python -m app.migrations status|up|down [--db PATH]`.

## Front end
One file, no build step. Conventions: CSS variables for theming (`--bg`, `--card`, …), `esc()` for every value inserted with `innerHTML`, `api()` wrapper adds the CSRF header, state polling in `refresh()`.
Several tests assert on CSS/JS snippets (they are cheap regression guards); when you change the markup, change the guard in the same commit. Layout is verified at 390 / 720 / 840 / 1024 / 1200 / 1440 px (see `docs/FOLDABLE.md`).

## Security checklist for changes
New route: needs `Depends(authed)` unless it must be public; POST/DELETE are CSRF-guarded by the middleware. New file access: never from client-supplied paths. New subprocess: fixed argv, no shell. Run `tools/audit_public.py`.

## Releasing
1. Update `CHANGELOG.md` and `app/__init__.py` (`__version__`).
2. `git tag vX.Y.Z && git push origin vX.Y.Z`. `.github/workflows/release.yml` runs the tests and the audit, builds `h3-studio-X.Y.Z.tar.gz` with `git archive`, writes a SHA-256 file and creates the GitHub release.

## Working with Claude Code
`CLAUDE.md` in the repo root tells Claude Code how this project is organised and what must never be committed. Typical prompts: *"add a field X to the generate form and API"*, *"translate the UI to English"*, *"support a new H3cApp endpoint"*. Ask it to run the tests and the audit before you commit.
