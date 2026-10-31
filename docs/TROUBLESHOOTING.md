# Troubleshooting

Start with `bin/h3studio doctor` and `bin/h3studio logs`.

| Symptom | Likely cause | Fix |
|---|---|---|
| Header pill says **H3 离线** / jobs wait with "H3cApp 未运行" | H3cApp is not running or its token file is missing | Open H3cApp. Check `ls ~/Library/Application Support/H3cApp/api-token`. A custom location needs `H3C_SUPPORT_DIR` or `H3C_TOKEN_FILE` |
| No models in the picker | none registered in H3cApp | In H3cApp: Model Manager → download/import/add a model. The list refreshes within seconds |
| Model card shows **INT8 缓存:未构建** and Fast INT8 is not offered | the INT8 cache is built per model, inside H3cApp | H3cApp → Advanced Settings → Compute mode → *Build Cache…* (M5-class GPU only; needs a lot of free disk per model: about 19 GB in the author's tests). H3 Studio never builds caches |
| "Fast INT8" not available at all | not an M5-class GPU | Use Resident mode; see `docs/INT8_CACHE.md` |
| Job fails: "模型切换失败" | H3cApp refused to switch (a manual generation was running) or the model vanished | Wait for the manual job; the job is kept, press retry. H3 Studio never uses another model instead |
| Job fails: "模型校验失败" | the engine had files of a different model open | Retry; if it repeats, restart H3cApp and report it with `bin/h3studio logs` |
| Jobs stay queued with a note about disk or memory | built-in guards | free disk (default threshold 15 GB) or close memory-heavy apps; thresholds are in `data/config.json` |
| `port 8195 is used by another process` | something else listens there | `H3STUDIO_PORT=8197 bin/h3studio start` |
| Can't log in; forgot password | | `bin/h3studio password` (or `rotate-password`, then `restart`) |
| Login works but you are logged out immediately (Safari, plain HTTP on another host) | Secure cookies need HTTPS | Use `http://127.0.0.1:8195` locally, or HTTPS (see `REMOTE-ACCESS.md`) |
| No thumbnails / previews | ffmpeg missing or without libx264 | `brew install ffmpeg`; `bin/h3studio doctor` shows what it found. Under a LaunchAgent PATH is limited; the template adds Homebrew paths |
| Video won't play in the browser | HEVC output, preview not made yet | Wait for `preview.mp4`; the original is always downloadable |
| Temperature/power tiles show "—" | macmon not installed/running | optional: `brew install macmon`, then run it **bound to loopback**: `macmon serve --host 127.0.0.1 --port 9197` (its default is `0.0.0.0`!) |
| Page looks tiny on a phone/foldable and a yellow hint appears | the browser is in **Desktop site** mode or zoomed out | browser menu → untick *Desktop site*, reload |
| Browser shows no "Install" option | PWA install needs HTTPS or `localhost`; some browsers hide it | use the header **安装** button for manual steps |
| `./install.sh` says Python 3.10 or newer is required | only macOS's built-in Python 3.9 found | `brew install python@3.12`, then `./install.sh` again |
| `bin/h3studio start` says Python dependencies are missing | install not run | `./install.sh` |
| After an update the app won't start | dependency change | `./install.sh` again; look at `logs/h3studio.log`; the database auto-migrates and keeps a backup in `data/backups/` |

## Collecting information for a bug report

```bash
bin/h3studio doctor --json > doctor.json     # contains no secrets
bin/h3studio logs 200                         # check for personal paths/prompts before sharing
```

Never paste `data/config.json` or the H3cApp token anywhere.

## Resetting

* Forget history and videos: stop the app, move `data/` away, start again (a new password is created).
* Keep videos but reset the queue: `sqlite3 data/jobs.sqlite "delete from jobs"` only if you accept losing metadata; the files in `data/library/` stay.
