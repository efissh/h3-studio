"""Config file handling and the pure helpers of the diagnostics."""
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def fresh_config(monkeypatch):
    d = Path(tempfile.mkdtemp()) / "data"
    monkeypatch.setenv("H3STUDIO_DATA", str(d))
    from app import config
    return config, d


def test_config_is_created_private_with_random_secrets(monkeypatch):
    config, d = fresh_config(monkeypatch)
    cfg = config.load_config()
    assert len(cfg["password"]) >= 12 and len(cfg["session_secret"]) == 64
    assert stat.S_IMODE(os.stat(d / "config.json").st_mode) == 0o600 and stat.S_IMODE(os.stat(d).st_mode) == 0o700
    assert config.load_config()["password"] == cfg["password"]                  # stable across runs
    assert cfg["secure_cookie"] is False and cfg["enable_ssd_streaming"] is False  # local-only, conservative defaults


def test_new_default_keys_are_added_to_old_configs_and_rotation_changes_secrets(monkeypatch):
    config, d = fresh_config(monkeypatch)
    cfg = config.load_config()
    del cfg["min_free_mem_pct"]
    (d / "config.json").write_text(json.dumps(cfg))
    assert config.load_config()["min_free_mem_pct"] == 20
    old = config.load_config()
    new_pw = config.rotate_secrets()
    assert new_pw != old["password"] and config.load_config()["session_secret"] != old["session_secret"]


def test_set_value_rejects_unknown_keys(monkeypatch):
    config, _ = fresh_config(monkeypatch)
    config.set_value("secure_cookie", True)
    assert config.load_config()["secure_cookie"] is True
    try:
        config.set_value("password", "x")
    except KeyError:
        pass
    else:
        raise AssertionError("secrets must not be settable through set_value")


def test_chip_and_hardware_advice():
    from app.doctor import advice, chip_info
    m5u = chip_info("Apple M5 Ultra", 96 * 2**30)
    assert m5u["generation"] == 5 and m5u["int8_cache_capable"] and m5u["memory_gb"] == 96 and m5u["family"] == "M5 Ultra"
    assert chip_info("Apple M5 Max", 128 * 2**30)["int8_cache_capable"]
    m2 = chip_info("Apple M2 Pro", 32 * 2**30)
    assert m2["apple_silicon"] and not m2["int8_cache_capable"]
    assert ("fail", "H3cApp needs an Apple Silicon Mac (Intel is not supported).") in advice(chip_info("Intel(R) Core(TM) i9", 32 * 2**30))
    assert any(s == "warn" for s, _ in advice(chip_info("Apple M1", 16 * 2**30)))              # below H3cApp's recommendation
    assert not any(s == "warn" for s, _ in advice(m5u))


def test_doctor_never_prints_the_h3capp_token(monkeypatch, capsys):
    tok = Path(tempfile.mkdtemp()) / "api-token"
    tok.write_text("SUPER-SECRET-TOKEN")
    monkeypatch.setenv("H3C_TOKEN_FILE", str(tok))
    monkeypatch.setenv("H3C_API_URL", "http://127.0.0.1:9")                                     # nothing listens: check must degrade gracefully
    import importlib
    from app import doctor
    importlib.reload(doctor)
    doctor.main()
    assert "SUPER-SECRET-TOKEN" not in capsys.readouterr().out
