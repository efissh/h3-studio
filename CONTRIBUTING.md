# Contributing

Thanks for helping. This is a small project; keep changes focused.

1. Fork, branch from `main`.
2. `./install.sh --dev`, then `.venv/bin/python -m pytest -q` (≈20 s; the end-to-end tests use the mock engine and need ffmpeg).
3. Follow the existing style: plain Python code that runs on 3.10–3.13 (`from __future__ import annotations`), no new runtime dependency without a strong reason (list it in `THIRD_PARTY_NOTICES.md`), no build step or CDN for the front end.
4. Add or update tests with the change. UI strings asserted by tests must be updated with the UI.
5. Before pushing run `python3 tools/audit_public.py`: it must report 0 findings. **Never commit** `data/`, `logs/`, models, videos, tokens, passwords, personal paths, hostnames or e-mail addresses.
6. Open a pull request describing what changed and how you tested it. CI must be green.

By contributing you agree that your contribution is licensed under the MIT license of this project.

## Ground rules for changes that touch safety
* Local-only by default. Anything that listens on a network address, adds an unauthenticated route, or reads/writes a path derived from user input needs a test and a note in `docs/SECURITY-MODEL.md`.
* Never fall back silently to a different model or compute mode; fail the job with a clear reason instead.
* Never show a made-up measurement: unknown values display "—".
