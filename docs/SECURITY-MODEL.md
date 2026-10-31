# Security model

H3 Studio is a **private, single-user tool for your own Mac**. It is not hardened for hostile networks.

## What is protected, and how
| Asset | Protection |
|---|---|
| The web UI and everything it shows | one shared password (`data/config.json`, random 16 chars, shown by `bin/h3studio password`); signed session cookie, `SameSite=Strict`, `HttpOnly`, 14-day lifetime; `Secure` flag when `secure_cookie` is true |
| State-changing requests | require header `X-Requested-With: h3studio` **and** a same-origin `Origin`; `SameSite=Strict` cookie |
| Password guessing | 5 failures per client address → 5-minute lockout (note: behind a proxy all clients share one address) |
| H3cApp's API token | read from H3cApp's own file on every call; never logged, never sent to the browser; `bin/h3studio doctor` only checks that it exists |
| H3cApp's API | stays on `127.0.0.1`; the browser can't reach it; this app is the only client |
| Network exposure | listens on `127.0.0.1`; the CLI refuses any other address unless `H3STUDIO_ALLOW_LAN=1` |
| Uploads | PNG/JPEG/WebP only, detected by magic bytes (file name and content-type are ignored), ≤ 15 MB, stored under server-generated names; jobs reference uploads by id, never by path |
| File access | the browser can only fetch media of jobs in the database, by job id; resolved paths must stay inside `data/library`; there is no endpoint that reads or writes arbitrary paths or runs commands |
| Models | the browser sends a model id; ids are validated against what H3cApp reports |
| Data at rest | `data/` is mode 700, config 600. **Not encrypted**: use FileVault; the password is stored in plain text in the config file (needed for a shared-secret check; anyone who can read your files can read it) |

Unauthenticated endpoints: `/` (the page itself), `/manifest.webmanifest`, `/pwa/icon-*.png`, `/api/session`, `/api/login`. Everything else answers 401.
There is deliberately no service worker and no offline cache.

## What it does **not** do
* No per-user accounts, roles or audit trail. Anyone with the password can generate, view, download and delete everything.
* No TLS of its own. Over a network use HTTPS from something else (Tailscale Serve, see [`REMOTE-ACCESS.md`](REMOTE-ACCESS.md)).
* No protection against someone who already controls your Mac account.
* No content moderation. See [`LICENSES.md`](LICENSES.md) for the model's rules; providing generation to other people triggers extra obligations.

## Exposing it
* **Don't** publish it on the internet, port-forward it, or use `tailscale funnel`.
* On a shared tailnet, restrict by identity: in `data/config.json` set `"allowed_ts_users": ["you@example.com"]`. The server then requires the
  `Tailscale-User-Login` header that **Tailscale Serve** adds. That header is only trustworthy when the app listens on loopback and Serve is the only way in; if the port is
  reachable any other way, anyone can forge it. Treat it as an extra layer, not the only one.
* On a LAN (`H3STUDIO_ALLOW_LAN=1`) traffic, including the password, is plain HTTP.

## macmon
`macmon serve` binds to `0.0.0.0` by default: always start it with `--host 127.0.0.1` (the provided LaunchAgent template does). H3 Studio only reads `http://127.0.0.1:9197/json`; the URL is fixed.

## Dependency advisories
`requirements.txt` is scanned with `pip-audit` in CI on every push and weekly. Minimum versions are set so that every advisory that touches code this app uses is fixed
(`python-multipart` handles uploads; `anyio`, `python-dotenv` had advisories too). That is why **Python 3.10+ is required**: the fixed releases do not exist for 3.9.

Five advisories on `starlette 0.52.1` are listed as ignored in `.github/workflows/ci.yml` after review. Why they do not apply here:

| Advisory | Issue | Why not applicable |
|---|---|---|
| PYSEC-2026-161, PYSEC-2026-248 | URL reconstructed from the `Host` header / an unvalidated path (`request.url`) | the app never uses `request.url`; its Origin check compares the raw `Host` header |
| PYSEC-2026-249 | `request.form()` ignores size limits for urlencoded bodies | the app never calls `request.form()`; login is JSON, uploads are multipart with its own 15 MB cap |
| PYSEC-2026-2280 | `HTTPEndpoint` dispatches arbitrary attribute names | no `HTTPEndpoint` classes; all routes are plain functions |
| PYSEC-2026-2281 | Windows `StaticFiles` SSRF via UNC paths | no `StaticFiles`; macOS only |

Re-evaluate when FastAPI/Starlette release versions that fix them (then remove the ignore flags).

## Reporting
See [`../SECURITY.md`](../SECURITY.md).
