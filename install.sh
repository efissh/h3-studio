#!/bin/bash
# H3 Studio installer. No sudo, no model downloads, does not touch H3cApp.
#   ./install.sh            create .venv, install dependencies, create data/config.json, run diagnostics
#   ./install.sh --dev      also install test dependencies
#   ./install.sh --launchd  also install the optional LaunchAgent (start at login)
set -euo pipefail
cd "$(dirname "$0")"
DEV=0; LAUNCHD=0
for a in "$@"; do case "$a" in --dev) DEV=1;; --launchd) LAUNCHD=1;; -h|--help) sed -n 2,6p "$0"; exit 0;; *) echo "unknown option: $a" >&2; exit 2;; esac; done

echo "== H3 Studio installer"
[ "$(uname -s)" = "Darwin" ] || echo "note: not macOS. The UI and tests work, but H3cApp (the video engine) only runs on Apple Silicon Macs."
[ "$(uname -m)" = "arm64" ] || echo "note: not an Apple Silicon (arm64) shell; H3cApp requires Apple Silicon."

PYBIN=""
for c in python3.13 python3.12 python3.11 python3.10 python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then PYBIN="$c"; break; fi
done
if [ -z "$PYBIN" ]; then
  echo "error: Python 3.10 or newer is required." >&2
  echo "       (macOS ships Python 3.9, whose newest dependency versions still carry known security advisories.)" >&2
  echo "       Install one:  brew install python@3.12     then re-run ./install.sh" >&2
  exit 1
fi
echo "python: $($PYBIN --version) ($(command -v $PYBIN))"

[ -d .venv ] || "$PYBIN" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
[ "$DEV" = 1 ] && .venv/bin/python -m pip install --quiet -r requirements-dev.txt
mkdir -p data logs
chmod +x bin/h3studio tools/mock_h3capp.py 2>/dev/null || true

echo "== first-run setup"
bin/h3studio setup

echo "== diagnostics (read-only)"
bin/h3studio doctor || true
[ "$LAUNCHD" = 1 ] && bin/h3studio launchagent-install

cat <<MSG

Next steps
  1. Install H3cApp separately (the video engine; it is not part of this project) and add a model in it:
       https://github.com/JunzoKamahara/H3cApp/releases      (read the MiniMax H3 license: docs/LICENSES.md)
  2. Open H3cApp once so it creates its local API token.
  3. bin/h3studio start        ->  http://127.0.0.1:8195   (password was printed above; bin/h3studio password)
  No GPU or model yet?  bin/h3studio demo   tries the interface with a mock engine.
MSG
