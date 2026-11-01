# Low-bandwidth mobile polling fix

The Android Clash/Mihomo + embedded-Tailscale handoff diagnosis identified:
- Real H3 /api/state payload: ~109 KB compressed with 72 recent records.
- Browser cadence: one full /api/state fetch every 2 seconds, even if prior calls are pending.
- Slow mobile DERP sample: ~10 KB/s; Wi-Fi recovered quickly.
- Real browser on mobile observed 100–136-second API calls, while light requests
  could complete in ~1.3 seconds.

This change addresses application-level amplification; it does **not** claim
to repair carrier NAT or DERP routing.

## APIs

- GET /api/state remains backwards-compatible and includes the last 200
  completed jobs for existing clients.
- GET /api/state?compact=1: **tiny** live snapshot: active jobs, live system
  metrics, H3 readiness, a history revision token. Does not serialize the
  historical list. Private HK also returns only up to 20 thin upscale records.
- GET /api/jobs/history?limit=30&offset=0: authenticated paged summaries;
  strips original file paths, bulky model snapshots, long prompt text and
  unneeded job parameters.
- GET /api/jobs/{32-character-hex-id}: authenticated full job detail for
  playback/re-generation; server-side filesystem paths never included.

## Browser behavior

- Only one live-state fetch may be pending at a time.
- A request which stalls for more than 12 seconds is aborted.
- Polls are *scheduled after* the prior response, not at fixed wall-clock
  intervals. ~5 seconds with ongoing work and ~15 seconds while idle.
- Backgrounded/hidden pages don't schedule new live-state requests. The tab
  resumes polling on visibility restoration.
- Full historical records are not fetched when simply opening the creation
  tab. Jobs/Library/RIFE tabs load summary pages on demand (30 per page).
- The **加载更多历史作品** button allows explicit pagination.
- Full video details are fetched only when a user opens one work item.
- Model choices are refreshed on demand and at most every 60 seconds when the
  creation tab is visible; duplicate model requests are prevented.
- No automatic retry of H3 generation POST calls, which could queue duplicates.

## Selective HTTP compression

The legacy 109KB state response was **uncompressed on the wire** in the
standalone vs embedded Tailscale test. The server now negotiates gzip via
the browser's normal `Accept-Encoding: gzip` header for selected JSON
GET endpoints: live state, history, individual job detail, model list,
upscale jobs and RIFE status/jobs. It uses Starlette's built-in gzip
middleware at compression level 5 and only for responses >= 512 bytes.

**Do not gzip MP4, thumbnails, uploads, PWA assets or streamed media.**
Clients that request `Accept-Encoding: identity` get unchanged JSON.
The previous compact-state/historical-pagination fix remains the main
bandwidth reduction. Gzip is an additional, backward-compatible saving.

A production validation must measure actual `Content-Encoding`, bytes
over the wire, `/api/state?compact=1` responsiveness and browser request
cadence on mobile data. Do not infer real carrier throughput from a local
unit test, and do not assume DERP speed itself is fixed by compression.

## Safety, rollback and validation

The code does not change H3cApp, model files, INT8 caches, user media, Clash,
Tailscale, the SQLite schema, or other Mac Studio services. API authentication,
CSRF protection and original download routes remain unchanged.

Run the full Python tests and a mobile browser smoke test on Wi-Fi and 5G.
Measure response sizes, actual live API request cadence, duplicate requests,
jobs/history paging, video playback, model choice, GPU/ETA, RIFE, and upscale.

Deploy only after confirming active H3 jobs and upscale queues are idle, and
restart only the Web Studio service. Rollback is a Git revert plus Web Studio
restart (no data migration).

Successful app-level acceptance: live-state responses must no longer scale
with the number of stored historical videos; no overlapping live requests; H3
is usable through a slow-but-functional relay. Measure the actual production
sizes, do not present an estimated percentage as a measured outcome.
