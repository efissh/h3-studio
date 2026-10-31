# Changelog

## 0.1.0: first public edition
Independent public edition of a private workbench; no shared history.

* Dynamic model discovery from H3cApp (no hard-coded models), per-job model snapshots, verified switching (API + open-file check), no silent fallback.
* Compute modes derived from H3cApp's real state (Resident, Fast INT8 cache when built, optional SSD streaming).
* FIFO queue with restart recovery, persisted library (original + H.264 preview + thumbnail), cancel/retry, disk and memory guards.
* Hardware telemetry (GPU/CPU/RAM; optional temperature/power via macmon), dark/light themes, PWA, phone/foldable layouts, "desktop site" detection hint.
* Local-only by default; optional Tailscale Serve helper; `bin/h3studio` CLI, `install.sh`, `doctor`, mock engine and demo mode.
* Security: password login, CSRF, upload validation, rate limit; `tools/audit_public.py` release audit.
* Interface text is Chinese only (see `docs/LOCALIZATION.md`).
