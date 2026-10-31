# Models and compute modes

## Models are discovered, not configured
H3 Studio lists whatever is registered in **H3cApp** (`GET /api/models`). Add, import or remove models in H3cApp's Model Manager; the list here follows within seconds.
Nothing in this repository names a specific model.

* **Model id.** `m-` plus a slug of the model *folder name* (for example folder `MiniMax-H3 GGUF` → `m-minimax-h3-gguf`). Ids therefore survive re-imports; two folders with the same name get a short suffix. Ids, not paths, are all the browser ever sends.
* **History is kept.** Each job stores its own snapshot (display name, description of the DiT and text encoder, H3cApp version). If a model is later removed, its jobs stay viewable and downloadable, show the saved name, and **cannot be retried or silently redirected to another model**. If you re-add a folder with the same name, retries work again.
* **Default model.** The model currently active in H3cApp, else the first available one.

## Switching, and proof that it worked
Before each job (GPU idle) the worker:
1. calls H3cApp's `POST /api/models/select` for the job's model if it is not already active;
2. re-reads `GET /api/models` and requires exactly that model to be active;
3. while the job runs, uses `lsof` on the H3cApp process to check that every model weight file it has open belongs to that model's folder and that any INT8 cache it has open belongs to that model's UUID.

Result is stored per job as `verified`: `api+lsof` (both agreed), or `api` (the engine had nothing conclusive open yet). A mismatch aborts the job with an error. A failed switch fails the job; **there is no fallback to another model or mode.**

> **Compatibility note.** `/api/models/select` and `/api/models/detail` exist in H3cApp 0.7.x but are not in its public `API.md`. They may change in a future H3cApp release; `tests/test_models.py` is the tripwire, and `docs/DEVELOPER.md` explains where to adapt.

## Compute modes
Offered per model, based on what H3cApp reports:

| Mode | Offered when | Notes |
|---|---|---|
| `resident` | always | whole DiT resident in unified memory; no cache needed; largest memory use |
| `attentionCache` ("Fast INT8 cache") | the model's INT8 cache is **built** and the GPU supports it (M5-class) | build it in H3cApp (Advanced Settings → Compute mode → Build Cache). Never offered otherwise; never substituted |
| `ssdStreaming` | you set `"enable_ssd_streaming": true` in `data/config.json` | H3cApp's low-memory mode; not performance-verified by this project |

The default for a model is `attentionCache` when available, otherwise `resident`. A job that asks for an unavailable mode is rejected (HTTP 400), not downgraded.
**M5 Fast attention** (a separate H3cApp option, on by default in the form) can change the composition of a video; it is independent of the compute mode and can be switched off per job.

## Hardware notes
`bin/h3studio doctor` prints the chip and unified memory it sees and what that implies. Memory requirements are defined by H3cApp and the model; consult H3cApp's documentation.
In the author's tests (M5 Ultra, 96 GB) the INT8 cache gave identical output to Resident with much lower memory use and only a small speed difference; see [`INT8_CACHE.md`](INT8_CACHE.md). Do not assume the same numbers on other machines.

## Getting models
Use H3cApp's own downloader. For scripted downloads of files you name yourself, `tools/fetch_hf_manifest.py` does resumable downloads with SHA-256 verification, and `tools/gguf_index.py` reads a GGUF header without loading the file. Check each model's license before use ([`LICENSES.md`](LICENSES.md)).
