# Installation

## 1. Prerequisites

| Need | How |
|---|---|
| Apple Silicon Mac, macOS 15+ | required by H3cApp |
| Python 3.10+ (3.12 recommended) | `python3 --version`. macOS ships 3.9, which is **not enough** (patched dependency versions need 3.10+): `brew install python@3.12` |
| ffmpeg | `brew install ffmpeg` (must include `libx264`; Homebrew's does) |
| **H3cApp** + a model | download from <https://github.com/JunzoKamahara/H3cApp/releases> (signed and notarised), open it, follow its setup wizard to download/import a model. Read the model license first: [`LICENSES.md`](LICENSES.md) |
| Open H3cApp once | it creates `~/Library/Application Support/H3cApp/api-token` and starts its local API on `127.0.0.1:8420` |

H3 Studio never downloads models and never modifies H3cApp.

## 2. Install H3 Studio

```bash
git clone https://github.com/efissh/h3-studio.git     # or download and unzip a release
cd h3-studio
./install.sh
```

`install.sh` (no `sudo`): finds Python ≥ 3.10, creates `.venv`, installs `requirements.txt`, creates `data/` and `logs/`, runs `bin/h3studio setup`
(writes `data/config.json` with a random password and prints it once) and finishes with `bin/h3studio doctor`.

Options: `--dev` (also install test tools), `--launchd` (also start at login via a per-user LaunchAgent).

## 3. Run

```bash
bin/h3studio start        # background, http://127.0.0.1:8195
bin/h3studio status
bin/h3studio password     # show the login password again
bin/h3studio logs
bin/h3studio stop
```

Open <http://127.0.0.1:8195>, log in, pick a model, write a prompt, press the generate button. Results appear in the library tab.

Start at login (optional): `bin/h3studio launchagent-install` (remove with `launchagent-uninstall`). It runs in your user session. H3cApp is a GUI app, so
it also needs your user to be logged in; there is no way to render without a logged-in session, and this project does not enable auto-login.

## 4. Check your setup

`bin/h3studio doctor` is read-only and prints one line per check: chip and memory, dependencies, ffmpeg, H3cApp app/process/token/API, number
of registered models, free disk, optional macmon/tailscale. `--json` gives machine-readable output.

## 5. Update

```bash
bin/h3studio update       # git clones: git pull --ff-only + refresh dependencies
bin/h3studio restart
```

Downloaded a release instead? Unpack the new release next to the old one, copy your `data/` directory into it, run `./install.sh`. The database migrates itself on start
(with an automatic backup in `data/backups/`).

## 6. Uninstall

`bin/h3studio launchagent-uninstall`, then delete the folder. Your videos live in `data/library/`: copy them out first if you want them.

## Where things are

| Path | What |
|---|---|
| `data/config.json` | password, session secret, thresholds (mode 600; never commit) |
| `data/jobs.sqlite` | queue and history |
| `data/library/` | videos, previews, thumbnails |
| `data/uploads/` | uploaded start/end frames |
| `data/backups/` | database backups made before migrations |
| `logs/h3studio.log` | server log |

## Choosing a port or data folder

`H3STUDIO_PORT=9000 bin/h3studio start`, `H3STUDIO_DATA=/Volumes/Fast/h3data bin/h3studio start`. Other settings: `bin/h3studio help`.
If H3cApp lives somewhere unusual: `H3C_APP_PATH`, `H3C_SUPPORT_DIR` (token and caches), `H3C_API_URL`, `H3C_TOKEN_FILE`.
