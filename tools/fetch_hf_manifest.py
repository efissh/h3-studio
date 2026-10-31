#!/usr/bin/env python3
"""Resumable, hash-verified download of a file manifest from a Hugging Face model repo.

    fetch_hf_manifest.py <repo> <manifest.json> <dest_dir> [strip_prefix]

manifest: [[path_in_repo, size, sha256_or_empty], ...]. Each file is fetched to `<name>.part` with
HTTP Range resume, verified (size, and SHA256 when the LFS hash is known) and only then renamed.
Stops at the first failure; never leaves an unverified file under its final name.
"""
import hashlib, json, os, sys, time, urllib.request
from pathlib import Path


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(repo: str, path: str, size: int, sha: str, dest: Path) -> None:
    final, part = dest, dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if final.exists() and final.stat().st_size == size and (not sha or sha256_of(final) == sha):
        print(f"[skip] {path}", flush=True)
        return
    url = f"https://huggingface.co/{repo}/resolve/main/{path}"
    while True:
        have = part.stat().st_size if part.exists() else 0
        if have == size:
            break
        req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "ab") as out:  # nosec B310: https://huggingface.co URL built above
            while True:
                buf = r.read(4 << 20)
                if not buf:
                    break
                out.write(buf)
        if part.stat().st_size < size:
            print(f"[retry] {path} at {part.stat().st_size}/{size}", flush=True)
            time.sleep(3)
    if part.stat().st_size != size:
        raise SystemExit(f"size mismatch {path}")
    if sha:
        got = sha256_of(part)
        if got != sha:
            raise SystemExit(f"SHA256 MISMATCH {path}: {got} != {sha}")
    os.replace(part, final)
    print(f"[ok]   {path} {size} {'sha256 verified' if sha else 'size verified'}", flush=True)


if __name__ == "__main__":
    repo, manifest, dest = sys.argv[1], json.load(open(sys.argv[2])), Path(sys.argv[3])
    strip = sys.argv[4] if len(sys.argv) > 4 else ""
    for path, size, sha in manifest:
        fetch(repo, path, size, sha, dest / (path[len(strip):] if strip and path.startswith(strip) else path))
    print("ALL DONE", flush=True)
