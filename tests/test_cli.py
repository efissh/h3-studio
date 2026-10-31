"""CLI safety behaviour, with a stub `tailscale` and nothing that touches launchd, the network or real data."""
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = str(ROOT / "bin" / "h3studio")


def env(**extra):
    d = Path(tempfile.mkdtemp())
    e = dict(os.environ, H3STUDIO_PYTHON=sys.executable, H3STUDIO_DATA=str(d / "data"), H3STUDIO_PORT="18195", PYTHONDONTWRITEBYTECODE="1")
    e.update(extra)
    return e, d


def run(*args, e=None, **kw):
    return subprocess.run([CLI, *args], capture_output=True, text=True, env=e or env()[0], timeout=60, **kw)


def stub_tailscale(d: Path, serve_status: str = "") -> Path:
    bindir = d / "bin"
    bindir.mkdir()
    log = d / "tailscale.log"
    t = bindir / "tailscale"
    t.write_text(f'#!/bin/bash\necho "$@" >> "{log}"\nif [ "$1" = serve ] && [ "$2" = status ]; then printf %s "{serve_status}"; fi\nexit 0\n')
    t.chmod(t.stat().st_mode | stat.S_IEXEC)
    return log


def test_refuses_to_listen_on_a_non_loopback_address_without_explicit_opt_in():
    e, _ = env(H3STUDIO_HOST="0.0.0.0")
    for cmd in ("start", "run", "launchagent-install"):
        r = run(cmd, e=e)
        assert r.returncode != 0 and "refusing to listen" in r.stderr, (cmd, r.stderr)
    assert "H3STUDIO_ALLOW_LAN" in run("start", e=e).stderr


def test_setup_creates_private_config_and_password_command_matches():
    e, d = env()
    r = run("setup", e=e)
    assert r.returncode == 0 and "password:" in r.stdout
    pw = r.stdout.split("password:")[1].split()[0]
    assert run("password", e=e).stdout.strip() == pw
    assert stat.S_IMODE(os.stat(d / "data" / "config.json").st_mode) == 0o600
    assert run("setup", e=e).stdout.count("password:") == 0              # a second run must not print or change it
    new = run("rotate-password", e=e).stdout
    assert pw not in new


def test_tailscale_on_uses_serve_only_never_funnel_and_never_overwrites_a_mapping():
    e, d = env()
    log = stub_tailscale(d, serve_status="https://x.ts.net:8443 (tailnet only)\n|-- / proxy http://127.0.0.1:3000\n")
    e["PATH"] = f"{d / 'bin'}:{e['PATH']}"
    run("setup", e=e)
    busy = run("tailscale-on", e=e)                                      # 8443 already mapped
    assert busy.returncode != 0 and "already has a mapping" in busy.stderr
    assert "--bg" not in log.read_text()                                  # nothing was changed
    ok = run("tailscale-on", "9443", e=e)
    assert ok.returncode == 0, ok.stderr
    calls = log.read_text()
    assert "serve --bg --https=9443 http://127.0.0.1:18195" in calls and "funnel" not in calls
    assert run("password", e=e).returncode == 0
    import json
    assert json.loads((d / "data" / "config.json").read_text())["secure_cookie"] is True
    run("tailscale-off", "9443", e=e)
    assert "serve --https=9443 off" in log.read_text()
    assert json.loads((d / "data" / "config.json").read_text())["secure_cookie"] is False


def test_tailscale_on_refuses_a_non_loopback_backend():
    e, d = env(H3STUDIO_HOST="0.0.0.0", H3STUDIO_ALLOW_LAN="1")
    stub_tailscale(d)
    e["PATH"] = f"{d / 'bin'}:{e['PATH']}"
    r = run("tailscale-on", e=e)
    assert r.returncode != 0 and "loopback" in r.stderr


def test_launchagent_template_renders_to_a_loopback_only_service():
    t = (ROOT / "deploy" / "io.github.h3studio.web.plist.template").read_text()
    out = t.replace("__ROOT__", "/opt/h3-studio").replace("__HOST__", "127.0.0.1").replace("__PORT__", "8195")
    assert "__" not in out and "<string>127.0.0.1</string>" in out and "0.0.0.0" not in out
    macmon = (ROOT / "deploy" / "io.github.h3studio.macmon.plist.template").read_text()
    assert "<string>--host</string><string>127.0.0.1</string>" in macmon.replace("\n  ", "")


def test_help_and_unknown_commands_do_not_crash_or_change_anything():
    assert "local-only" in run("help").stdout.lower() or "127.0.0.1" in run("help").stdout
    assert run("definitely-not-a-command").returncode == 0               # prints help
