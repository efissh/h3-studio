"""Offline tests for ModelManager and migrations (fake H3cApp, temp DB)."""
import json, os, sqlite3, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest  # noqa: E402
from app import migrations  # noqa: E402
from app.models import ModelError, ModelManager, slug  # noqa: E402

OLD_SCHEMA = """CREATE TABLE jobs(id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at REAL NOT NULL, started_at REAL,
finished_at REAL, params TEXT NOT NULL, prompt TEXT, seed TEXT, stage TEXT, progress REAL DEFAULT 0, eta REAL, error TEXT,
video_path TEXT, thumb_path TEXT, preview_path TEXT, gen_seconds REAL, note TEXT, cancel_requested INTEGER DEFAULT 0, retry_of TEXT)"""


def old_db(tmp):
    c = sqlite3.connect(Path(tmp) / "jobs.sqlite", isolation_level=None)
    c.execute(OLD_SCHEMA)
    c.execute("INSERT INTO jobs(id,status,created_at,params,prompt,seed,video_path,gen_seconds) VALUES('a','done',1,'{}','fox','7','/x/original.mp4',71)")
    return c


def test_migration_up_backfills_and_down_restores():
    with tempfile.TemporaryDirectory() as tmp:
        c = old_db(tmp)
        assert migrations.migrate(c, Path(tmp)) == migrations.LATEST
        r = c.execute("SELECT model_id, model_info, video_path, gen_seconds FROM jobs").fetchone()
        assert r[0] == "legacy" and json.loads(r[1])["backfilled"] and r[2] == "/x/original.mp4" and r[3] == 71
        assert list((Path(tmp) / "backups").glob("jobs-v0-before-*.sqlite"))      # backup taken first
        assert migrations.migrate(c, Path(tmp), 0) == 0                             # rollback
        cols = [x[1] for x in c.execute("PRAGMA table_info(jobs)")]
        assert "model_id" not in cols and "video_path" in cols
        assert c.execute("SELECT video_path FROM jobs").fetchone()[0] == "/x/original.mp4"


def test_migration_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        c = old_db(tmp)
        migrations.migrate(c, Path(tmp)); migrations.migrate(c, Path(tmp))
        assert migrations.version(c) == migrations.LATEST


class FakeH3:
    """Minimal H3cApp: GET /api/models, POST /api/models/select, GET /api/models/detail."""

    def __init__(self, names=("Alpha Q8", "Beta BF16"), active="Alpha Q8", built=(), refuse=False, ignore_select=False, int8=True):
        self.models = {n: {"id": f"id-{i}", "name": n, "path": f"/models/{n}", "active": n == active} for i, n in enumerate(names)}
        self.built, self.refuse, self.ignore, self.int8, self.selects = built, refuse, ignore_select, int8, []

    def __call__(self, method, path, **kw):
        if path == "/api/models":
            return SimpleNamespace(status_code=200, json=lambda: list(self.models.values()), text="")
        if path.startswith("/api/models/detail"):
            folder = next(n for n, m in self.models.items() if m["id"] == path.split("id=")[1])
            ok = folder in self.built
            fast = ("Available: the cache is built" if ok else "Available after “Build Cache…” in Advanced Settings (M5 only)") if self.int8 \
                else "Not available on this Mac (needs an M5-class GPU)"
            rows = [{"title": "Fast mode (M5 int8 cache)", "status": "ok" if ok else "info", "lines": [fast]},
                    {"title": "DiT", "status": "ok", "lines": ["GGUF · Q8_0 · 21.44 GB"]},
                    {"title": "Text encoder", "status": "ok", "lines": ["GGUF · Q8_0 · 27.49 GB"]},
                    {"title": "int8 cache (FL2VA)", "status": "ok" if ok else "info", "lines": ["19.28 GB" if ok else "Not built yet"]}]
            return SimpleNamespace(status_code=200, json=lambda: {"sections": [{"title": "x", "rows": rows}]}, text="")
        if path == "/api/models/select":
            self.selects.append(kw["json"]["id"])
            if self.refuse:
                return SimpleNamespace(status_code=409, json=lambda: {"error": "a generation is running"}, text="busy")
            if not self.ignore:
                for m in self.models.values():
                    m["active"] = m["id"] == kw["json"]["id"]
            return SimpleNamespace(status_code=200, json=lambda: {"ok": True}, text="")
        raise AssertionError(path)


A, B = "m-alpha-q8", "m-beta-bf16"


def test_ids_come_from_folder_names_not_from_h3capp_uuids():
    assert slug("Sakura H3 Q8 (experimental)") == "sakura-h3-q8-experimental" and slug("???") == "model"
    ids = [m["id"] for m in ModelManager(FakeH3()).list()]
    assert ids == [A, B]
    raw = [{"id": "AAAAAA-1", "name": "Same", "path": "/x/a/Same", "active": True},
           {"id": "BBBBBB-2", "name": "Same", "path": "/x/b/Same", "active": False}]       # two folders, same name
    twin_ids = list(ModelManager(lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: raw, text=""))._index())
    assert len(set(twin_ids)) == 2 and all(i.startswith("m-same") for i in twin_ids)       # disambiguated, still stable


def test_default_is_active_model_and_missing_h3capp_gives_none():
    assert ModelManager(FakeH3(active="Beta BF16")).default_id() == B
    assert ModelManager(FakeH3(names=())).default_id() is None

    def down(*a, **k):
        raise OSError("connection refused")
    mm = ModelManager(down)
    assert mm.list() == [] and mm.default_id() is None


def test_switch_selects_target_and_verifies():
    f = FakeH3(); mm = ModelManager(f)
    snap = mm.ensure_active(B)
    assert f.selects == ["id-1"] and snap["id"] == B and snap["folder"] == "Beta BF16"
    assert [n for n, m in f.models.items() if m["active"]] == ["Beta BF16"]


def test_no_select_when_already_active():
    f = FakeH3(); ModelManager(f).ensure_active(A)
    assert f.selects == []


def test_refused_switch_raises_and_never_falls_back():
    f = FakeH3(refuse=True)
    with pytest.raises(ModelError, match="拒绝切换"):
        ModelManager(f).ensure_active(B)
    assert f.models["Alpha Q8"]["active"]                    # untouched, nothing silently chosen


def test_switch_that_does_not_take_effect_is_detected():
    with pytest.raises(ModelError, match="激活模型不符"):
        ModelManager(FakeH3(ignore_select=True)).ensure_active(B)


def test_unknown_removed_or_malicious_ids_are_rejected_everywhere():
    mm = ModelManager(FakeH3())
    for bad in ("m-removed-model", "../../etc/passwd", "", None, "Alpha Q8", "m-" + "x" * 80):
        with pytest.raises(ModelError):
            mm.validate_choice(bad)
    for call in (mm.ensure_active, mm.get, mm.snapshot):
        with pytest.raises(ModelError):
            call("m-removed-model")
    with pytest.raises(ModelError):
        mm.validate_mode("m-removed-model", "resident")


def test_history_of_a_removed_model_is_not_silently_remapped():
    mm = ModelManager(FakeH3(names=("Beta BF16",), active="Beta BF16"))               # "Alpha Q8" was removed
    assert mm.display(A) == A                                                          # falls back to the id, never to another model
    with pytest.raises(ModelError, match="不会改用其他模型"):
        mm.get(A)


def test_modes_follow_what_h3capp_reports_for_each_model():
    mm = ModelManager(FakeH3(built=("Alpha Q8",)))
    a, b = mm.get(A), mm.get(B)
    assert a["compute_modes"] == ["resident", "attentionCache"] and a["default_compute_mode"] == "attentionCache" and a["cache_built"]
    assert a["cache_bytes"] == 19_280_000_000 and a["mode_labels"]["attentionCache"]
    assert b["compute_modes"] == ["resident"] and b["default_compute_mode"] == "resident" and not b["cache_built"]
    assert mm.validate_mode(A, None) == "attentionCache" and mm.validate_mode(B, None) == "resident"


def test_int8_is_never_offered_without_a_built_cache_or_on_unsupported_hardware():
    mm = ModelManager(FakeH3(built=()))
    with pytest.raises(ModelError, match="不可用"):
        mm.validate_mode(A, "attentionCache")                    # no silent downgrade, no silent upgrade
    nom5 = ModelManager(FakeH3(built=("Alpha Q8",), int8=False))
    assert nom5.get(A)["compute_modes"] == ["resident"] and not nom5.get(A)["supports_int8_cache"]


def test_ssd_streaming_is_opt_in_and_unknown_modes_are_rejected():
    assert "ssdStreaming" not in ModelManager(FakeH3()).get(A)["compute_modes"]
    on = ModelManager(FakeH3(), enable_ssd_streaming=True)
    assert on.validate_mode(A, "ssdStreaming") == "ssdStreaming"
    for bad in ("../x", "turbo", 5):
        with pytest.raises(ModelError):
            on.validate_mode(A, bad)


def test_quantization_and_format_come_from_h3capp_detail():
    m = ModelManager(FakeH3()).get(A)
    assert "GGUF · Q8_0" in m["quantization"] and m["dit_format"] == "gguf"


class _Out:
    def __init__(self, text): self.stdout = text


def _lsof(monkeypatch, mm, lines, engine_pid="123"):
    """Pretend the API port is served by `engine_pid` and that its open files are `lines`."""
    import subprocess
    monkeypatch.setattr(mm, "_engine_pid", lambda: engine_pid)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Out("\n".join("n" + x for x in lines)))


def test_verify_loaded_accepts_only_own_folder_and_own_cache(monkeypatch):
    from app import models as M
    mm = ModelManager(FakeH3(built=("Alpha Q8", "Beta BF16")))
    cache = lambda uuid: f"{M.SUPPORT_DIR}/cache/{uuid}/dit_int8_v2.cache"
    own = ["/models/Beta BF16/FL2VA/text_encoder/model.gguf", cache("id-1")]
    _lsof(monkeypatch, mm, own);                                               assert mm.verify_loaded(B) is True
    _lsof(monkeypatch, mm, own[:1] + [cache("id-0")]);                         assert mm.verify_loaded(B) is False      # another model's cache
    _lsof(monkeypatch, mm, ["/models/Alpha Q8/FL2VA/transformer/model.gguf"]); assert mm.verify_loaded(B) is False      # another model's weights
    _lsof(monkeypatch, mm, own + ["/models/Alpha Q8/x.gguf"]);                 assert mm.verify_loaded(B) is False
    _lsof(monkeypatch, mm, ["/tmp/unrelated"]);                                assert mm.verify_loaded(B) is None
    assert mm.verify_loaded("m-removed-model") is None


def test_verification_only_inspects_the_process_that_serves_the_api_port(monkeypatch):
    """A mock/tunnelled API must never be checked against some unrelated H3cApp process that happens to be running."""
    import subprocess
    mm = ModelManager(FakeH3(built=("Alpha Q8",)), api_url="http://127.0.0.1:18421")
    assert mm._port == 18421
    seen = []

    def fake_run(argv, **k):
        seen.append(argv)
        return _Out("p4242\ncPython\n")                           # the API port is served by a Python mock, not H3cApp
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert mm._engine_pid() is None and mm.verify_loaded(A) is None
    assert any("-iTCP:18421" in a for a in seen[0])
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: _Out("p777\ncH3cApp\n"))
    assert mm._engine_pid() == "777"
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: (_ for _ in ()).throw(OSError("no lsof")))
    assert mm._engine_pid() is None
