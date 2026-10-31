#!/usr/bin/env python3
"""Pre-publication audit of the working tree.   python3 tools/audit_public.py [DIR] [--extra-patterns FILE]

Looks for things that must never be in a public repository: credentials, private network identifiers, personal
paths/e-mail addresses, model weights / caches / media / databases, oversized files. Exit status 1 on any finding.
A line may opt out with the marker `audit:allow` (use sparingly, e.g. for documentation placeholders).

`--extra-patterns FILE` takes one regular expression per line (e.g. your own hostnames or IPs) so that private identifiers
can be scanned for without ever being committed. The file must stay outside the repository.
"""
import re
import subprocess
import sys
from pathlib import Path

MAX_BYTES = 1_500_000
BAD_SUFFIX = {".gguf", ".safetensors", ".cache", ".mp4", ".mov", ".m4v", ".sqlite", ".sqlite3", ".db", ".dmg", ".pem", ".key", ".p12",
              ".pt", ".ckpt", ".bin", ".zip", ".tar", ".gz", ".wav", ".mp3"}
BAD_NAMES = {"api-token", ".env", "config.json", "id_rsa", "id_ed25519", ".DS_Store", "credentials.json"}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "data", "logs", "downloads"}

RULES = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("api-secret", re.compile(r"\b(sk|rk)-[A-Za-z0-9]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("hardcoded-secret", re.compile(r"""(?i)\b(password|passwd|secret|token|api[_-]?key)\b\s*[:=]\s*['"][^'"\s]{8,}['"]""")),
    ("tailnet-hostname", re.compile(r"\b[a-z0-9-]+\.tail[0-9a-f]{4,}\.ts\.net\b")),
    ("tailscale-ip", re.compile(r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b")),
    ("lan-ip", re.compile(r"\b(192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")),
    ("home-path", re.compile(r"/Users/(?!<|you\b|name\b|me\b|user\b|\$|\{|Shared\b)[A-Za-z0-9._-]+")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com\b|example\.(com|org)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]
# Documentation may legitimately show these exact placeholders.
ALLOWED_EMAIL_LOCALS = {"noreply"}


def tracked_files(root: Path):
    """Files git would add (respects .gitignore) when inside a repo, otherwise every file outside SKIP_DIRS."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            return [root / f for f in out.stdout.splitlines()]
    except Exception:
        pass
    return [p for p in root.rglob("*") if p.is_file() and not (set(p.relative_to(root).parts) & SKIP_DIRS)]


def audit(root: Path, extra=()) -> list:
    findings = []
    extra_rules = [("private-identifier", re.compile(x)) for x in extra]
    for f in tracked_files(root):
        rel = f.relative_to(root)
        if not f.is_file():
            continue
        if f.suffix.lower() in BAD_SUFFIX or f.name in BAD_NAMES:
            findings.append((str(rel), 0, "forbidden-file", f.name))
            continue
        if f.stat().st_size > MAX_BYTES:
            findings.append((str(rel), 0, "oversized-file", f"{f.stat().st_size} bytes"))
            continue
        try:
            text = f.read_text(errors="strict")
        except (UnicodeDecodeError, OSError):
            if f.suffix.lower() not in {".png", ".ico", ".jpg", ".jpeg", ".gif", ".webp"}:
                findings.append((str(rel), 0, "binary-file", f.suffix or f.name))
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if "audit:allow" in line:
                continue
            for name, rx in RULES + extra_rules:
                m = rx.search(line)
                if m and not (name == "email" and m.group(0).split("@")[0] in ALLOWED_EMAIL_LOCALS):
                    findings.append((str(rel), n, name, m.group(0)[:60]))
    return findings


def main() -> int:
    args = sys.argv[1:]
    extra = []
    if "--extra-patterns" in args:
        i = args.index("--extra-patterns")
        extra = [l.strip() for l in Path(args[i + 1]).read_text().splitlines() if l.strip() and not l.startswith("#")]
        del args[i:i + 2]
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parent.parent
    res = audit(root, extra)
    for rel, n, rule, what in res:
        print(f"{rel}{':' + str(n) if n else ''}  [{rule}]  {what}")
    print(f"audit: {len(res)} finding(s) in {root}")
    return 1 if res else 0


if __name__ == "__main__":
    raise SystemExit(main())
