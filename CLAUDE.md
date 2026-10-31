# H3 Studio: notes for Claude Code (and other coding assistants)

Self-hosted web UI in front of **H3cApp**'s local API (MiniMax H3 video generation on Apple Silicon). FastAPI backend (`app/`), one-file vanilla front end (`static/index.html`), SQLite.
No build step, no npm, no CDN. Python 3.10+ (matches the patched dependency versions). Read `docs/DEVELOPER.md` first.

## Commands
- Setup: `./install.sh --dev`   Tests: `.venv/bin/python -m pytest -q`   Audit: `python3 tools/audit_public.py`
- Run: `bin/h3studio run` (foreground, reload) · try without a GPU/model: `bin/h3studio demo` (mock engine in `tools/mock_h3capp.py`)
- Environment check: `bin/h3studio doctor`

## Hard rules
1. **Never commit** `data/`, `logs/`, `.venv/`, model files (`*.gguf`, `*.safetensors`, `*.cache`), videos, databases, tokens, passwords, personal paths, hostnames, IP addresses, e-mail addresses. Run `python3 tools/audit_public.py` (must say 0 findings) before every commit.
2. **Local-only by default.** Do not change the default bind address from `127.0.0.1`, add unauthenticated routes, or add telemetry/outbound calls. Public routes are only `/`, `/manifest.webmanifest`, `/pwa/icon-*.png`, `/api/session`, `/api/login`.
3. The browser never supplies file paths or model paths: only job ids, upload ids and model ids validated server-side.
4. **No silent fallback.** A job whose model or compute mode is unavailable fails with a clear message; never substitute another.
5. Never display invented numbers: unknown sensor values are `None` in the API and "—" in the UI.
6. Do not restart or reconfigure H3cApp from code. H3 Studio only reads its state and calls its documented/observed API.
7. Keep dependencies minimal; any new one must be added to `requirements.txt` and `THIRD_PARTY_NOTICES.md` with its license.

## Where to change what
- Add a generate-form field: `clean_params()` and `h3_body()` in `app/main.py`, the form + `formParams()` in `static/index.html`, a test in `tests/test_api.py`.
- Model/compute-mode behaviour: `app/models.py` + `tests/test_models.py`. H3cApp API drift: adapt `_detail()`, update `tools/mock_h3capp.py`.
- Database: reversible step in `app/migrations.py`.
- UI text is Chinese (see `docs/LOCALIZATION.md`); tests assert on some strings, update them together.
- Layout breakpoints and guards: `docs/FOLDABLE.md`, `tests/test_foldable_layout.py`, `tests/test_ui_design.py`.

## Style
Small, direct functions; comments explain *why*. Match the surrounding code. Prefer extending existing tests over adding new files. Every user-visible `innerHTML` value goes through `esc()`.
