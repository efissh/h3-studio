"""The public-release audit itself must work: clean on this repo, loud on a poisoned tree."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import audit_public  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_repository_passes_its_own_audit():
    assert audit_public.audit(ROOT) == []


def test_audit_catches_the_things_that_must_never_be_published():
    d = Path(tempfile.mkdtemp())
    # Fixtures are assembled at run time so this file itself contains none of the literals the audit looks for.
    bad = "\n".join([
        "PASS" + 'WORD = "hunter2hunter2"',
        "TOKEN = " + '"gh' + "p_" + "a" * 36 + '"',
        'h = "myhost.' + "tail" + '1a2b3c.ts.net"',
        'ip = "' + "100." + '101.102.103"',
        'p = "/Users' + '/alice/Developer"',
        'mail = "alice' + '@gmail.com"',
        'lan = "' + "192." + '168.1.20"',
        "-----BEGIN RSA PRIV" + "ATE KEY-----",
    ])
    (d / "a.py").write_text(bad + "\n")
    (d / "model.gguf").write_bytes(b"x")
    (d / "api-token").write_text("abc")
    (d / "clip.mp4").write_bytes(b"x")
    (d / "ok.md").write_text("contact: noreply@users.noreply.github.com, example: /Users/<you>/x, http://127.0.0.1:8195 \n# audit:allow " + "192." + "168.0.1\n")
    rules = {f[2] for f in audit_public.audit(d)}
    assert {"hardcoded-secret", "github-token", "tailnet-hostname", "tailscale-ip", "home-path", "email", "lan-ip",
            "private-key", "forbidden-file"} <= rules
    assert not [f for f in audit_public.audit(d) if f[0] == "ok.md"]                  # placeholders and opt-outs are fine


def test_extra_patterns_find_private_identifiers_without_committing_them(tmp_path):
    (tmp_path / "x.txt").write_text("my-secret-hostname\n")
    assert audit_public.audit(tmp_path, [r"my-secret-hostname"])[0][2] == "private-identifier"
    assert audit_public.audit(tmp_path) == []


def test_cli_exit_codes():
    clean = Path(tempfile.mkdtemp()); (clean / "a.txt").write_text("hello\n")
    dirty = Path(tempfile.mkdtemp()); (dirty / "a.txt").write_text("SECR" + 'ET = "abcdefgh12345"\n')
    run = lambda d: subprocess.run([sys.executable, str(ROOT / "tools/audit_public.py"), str(d)], capture_output=True, text=True).returncode
    assert run(clean) == 0 and run(dirty) == 1
