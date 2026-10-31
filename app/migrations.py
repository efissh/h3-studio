"""Reversible SQLite migrations keyed on PRAGMA user_version. A backup copy is taken before every change.

    python -m app.migrations status|up|down [--db PATH]
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

# Rows created before per-job models existed (only possible when upgrading an old database) get a neutral marker.
BACKFILL = json.dumps({"id": "legacy", "display": "(earlier model, not recorded)", "folder": "", "engine": "h3capp",
                       "quantization": "", "backfilled": True}, ensure_ascii=False)

# version -> (up statements, down statements)
MIGRATIONS = {
    1: (
        ["ALTER TABLE jobs ADD COLUMN model_id TEXT", "ALTER TABLE jobs ADD COLUMN model_info TEXT",
         "ALTER TABLE jobs ADD COLUMN out_w INTEGER", "ALTER TABLE jobs ADD COLUMN out_h INTEGER",
         "ALTER TABLE jobs ADD COLUMN verified TEXT", "ALTER TABLE jobs ADD COLUMN ab_group TEXT",
                  ("UPDATE jobs SET model_id='legacy', model_info=? WHERE model_id IS NULL", (BACKFILL,)),
         "CREATE INDEX IF NOT EXISTS idx_jobs_model ON jobs(model_id)"],
        ["DROP INDEX IF EXISTS idx_jobs_model", "ALTER TABLE jobs DROP COLUMN ab_group",
         "ALTER TABLE jobs DROP COLUMN verified", "ALTER TABLE jobs DROP COLUMN out_h",
         "ALTER TABLE jobs DROP COLUMN out_w", "ALTER TABLE jobs DROP COLUMN model_info",
         "ALTER TABLE jobs DROP COLUMN model_id"],
    ),
}
LATEST = max(MIGRATIONS)


def version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def backup(conn: sqlite3.Connection, dest_dir: Path, tag: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    p = dest_dir / f"jobs-{tag}-{time.strftime('%Y%m%d-%H%M%S')}.sqlite"
    dst = sqlite3.connect(p)
    conn.backup(dst)
    dst.close()
    return p


def _run(conn, stmts):
    for s in stmts:
        if isinstance(s, tuple):
            conn.execute(s[0], s[1])
        else:
            conn.execute(s)


def migrate(conn: sqlite3.Connection, data_dir: Path, target: int = LATEST) -> int:
    """Move to `target` (up or down) inside one transaction; returns the new version."""
    cur = version(conn)
    if cur == target:
        return cur
    backup(conn, data_dir / "backups", f"v{cur}-before")
    steps = range(cur + 1, target + 1) if target > cur else range(cur, target, -1)
    conn.execute("BEGIN")
    try:
        for v in steps:
            _run(conn, MIGRATIONS[v][0] if target > cur else MIGRATIONS[v][1])
        conn.execute(f"PRAGMA user_version={target}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return target


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    db = Path(sys.argv[sys.argv.index("--db") + 1]) if "--db" in sys.argv else Path(__file__).resolve().parent.parent / "data/jobs.sqlite"
    c = sqlite3.connect(db, isolation_level=None)
    print("db", db, "version", version(c), "latest", LATEST)
    if cmd == "up":
        print("->", migrate(c, db.parent, LATEST))
    elif cmd == "down":
        print("->", migrate(c, db.parent, max(version(c) - 1, 0)) if version(c) else "already at 0")
