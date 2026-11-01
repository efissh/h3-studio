"""RIFE frame schedule, release notices, and integration security regressions.

No GPU, Metal, FFmpeg subprocesses, or GitHub calls are needed.
"""
from fractions import Fraction
from pathlib import Path

from app.rife_video import _plan, TARGET_FPS, MAX_SECONDS
from app.interpolation import PINNED_ENGINE, latest_release, version_tuple


def test_24fps_to_60fps_uses_exact_source_timestamps():
    count, originals, pairs = _plan(120, Fraction(24), 60)
    assert count == 300
    assert originals[0] == 0
    assert originals[5] == 2
    assert originals[299] == 119
    assert [j for j, _ in pairs[0]] == [1, 2]
    assert [round(t, 2) for _, t in pairs[0]] == [0.4, 0.8]


def test_24fps_to_48fps_keeps_every_source_frame():
    count, originals, pairs = _plan(120, Fraction(24), 48)
    assert count == 240
    assert len(originals) == 121  # final output timestamp holds the last source frame
    assert pairs[0] == [(1, 0.5)]
    assert originals[239] == 119


def test_fractional_23_976fps_has_no_float_drift():
    count, originals, pairs = _plan(120, Fraction(24000, 1001), 60)
    assert count == 301
    assert len(originals) + sum(map(len, pairs.values())) == count


def test_invalid_interpolation_rate():
    import pytest
    with pytest.raises(ValueError):
        _plan(120, Fraction(60), 60)
    with pytest.raises(ValueError):
        _plan(1, Fraction(24), 60)


def test_release_notice_is_version_only_not_auto_update():
    assert version_tuple(PINNED_ENGINE) == (0, 1, 8)
    result = latest_release(lambda: {"tag_name": "v0.1.9"})
    assert result["update_available"] is True
    assert result["latest"] == "v0.1.9"
    assert result["release_url"] == "https://github.com/cinemore/rife-metal/releases"
    assert latest_release(lambda: {"tag_name": "v0.1.8"})["update_available"] is False
    assert latest_release(lambda: {"tag_name": "v0.1.7"})["update_available"] is False
    assert latest_release(lambda: {"tag_name": "https://other-site/malware"})["release_url"] is None


def test_frontend_is_authenticated_opt_in_and_preserves_existing_features():
    root = Path(__file__).resolve().parents[1]
    html = (root / "static/index.html").read_text()
    code = (root / "app/main.py").read_text()
    worker = (root / "tools/rife_stream/Sources/h3-rife-stream/main.swift").read_text()
    for marker in ['id="tab-rife"', 'id="rifeRun"', 'id="rifeSource"',
                   'id="rifeFPS"', 'id="rifeUpgrade"', 'id="rifeUpdateDot"']:
        assert marker in html
    assert "beforeinstallprompt" in html
    assert "modelGone(j)" in html
    assert "INTERPOLATION = register_interpolation" in code
    assert "H3_RIFE_WORKER" in (root / "app/interpolation.py").read_text()
    assert "configuration: .bundled(qualityTier: .hq)" in worker


def test_all_interpolation_routes_require_authentication():
    root = Path(__file__).resolve().parents[1]
    code = (root / "app/interpolation.py").read_text()
    assert code.count("dependencies=[Depends(authed)]") == 5
    assert "urllib.request.urlopen(req, timeout=4)" in code
    assert "os.replace(partial, destination)" in (root / "app/rife_video.py").read_text()


def test_frame_extraction_avoids_ffmpeg_flags_removed_in_ffmpeg_9():
    source = (Path(__file__).resolve().parents[1] / "app" / "rife_video.py").read_text()
    assert '"-vsync"' not in source
    assert '"-fps_mode", "passthrough"' in source
