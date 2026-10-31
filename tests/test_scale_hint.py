"""Desktop-site / zoomed-out page detection: static contract + (optional) real execution of the pure function."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parent.parent / "static" / "index.html"
HTML = UI.read_text()


def _function_source() -> str:
    a, b = HTML.index("/*scaleCheck:start*/"), HTML.index("/*scaleCheck:end*/")
    return HTML[a:b]


def test_hint_markup_and_dismiss_are_present_and_hidden_by_default():
    assert 'id="scaleHint" class="scale-hint hide"' in HTML          # never visible until detection says so
    for ident in ("scaleHintTitle", "scaleHintText", "scaleHintDiag", "scaleHintClose"):
        assert f'id="{ident}"' in HTML
    assert 'role="status"' in HTML.split('id="scaleHint"')[1][:120]
    assert "桌面版网站" in HTML and "取消勾选" in HTML


def test_hint_only_for_touch_devices_and_never_blocks_the_app():
    assert "matchMedia('(pointer:coarse)')" in HTML                   # desktop windows may span monitors
    assert "sessionStorage" in HTML and "catch(_)" in HTML.split("scaleHintClose")[2][:200]
    assert ".scale-hint button{flex:none;min-height:44px" in HTML     # touch-sized dismiss button
    assert "overflow-wrap:anywhere" in HTML                           # long diagnostics must not overflow the page


def test_hint_is_evaluated_after_login_and_on_resize_zoom_rotation():
    assert "scaleHintUpdate();refresh();" in HTML
    for ev in ("addEventListener('resize'", "addEventListener('orientationchange'", "visualViewport.addEventListener('resize'"):
        assert ev in HTML
    assert "window.__h3ScaleCheck" in HTML                            # lets the user run the diagnosis in a console


def test_no_new_network_or_storage_beyond_session_flag():
    block = HTML[HTML.index("/*scaleCheck:start*/"): HTML.index("window.__h3ScaleCheck")]
    assert "fetch(" not in block and "localStorage" not in block and "XMLHttpRequest" not in block


CASES = [  # (name, inputs, expected scaled, expected cause)
    ("normal unfolded portrait", dict(innerW=840, innerH=1000, screenW=840, screenH=1100, vvScale=1), False, None),
    ("normal phone portrait", dict(innerW=390, innerH=700, screenW=390, screenH=844, vvScale=1), False, None),
    ("phone landscape, screen.width fixed (iOS)", dict(innerW=844, innerH=340, screenW=390, screenH=844, vvScale=1), False, None),
    ("desktop-site on 840px screen (layout 980)", dict(innerW=980, innerH=1307, screenW=840, screenH=1120, vvScale=1), True, "desktop-site"),
    ("desktop-site on 720px screen (layout 1280)", dict(innerW=1280, innerH=1707, screenW=720, screenH=960, vvScale=1), True, "desktop-site"),
    ("desktop-site but screen as wide as layout", dict(innerW=980, innerH=1300, screenW=1024, screenH=1366, vvScale=1), False, None),
    ("pinched out to 70%", dict(innerW=840, innerH=1000, screenW=840, screenH=1100, vvScale=0.7), True, "zoomed-out"),
    ("split-screen half window", dict(innerW=420, innerH=1000, screenW=840, screenH=1100, vvScale=1), False, None),
    ("tiny but in tolerance (0.9)", dict(innerW=933, innerH=1200, screenW=840, screenH=1100, vvScale=1), False, None),
    ("missing metrics", dict(innerW=0, innerH=0, screenW=0, screenH=0, vvScale=1), False, None),
]


def test_scale_check_logic_when_node_available():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is optional; the same cases are exercised in a browser by hand")
    script = _function_source() + "\nconst cases=" + json.dumps([c[1] for c in CASES]) + \
        ";console.log(JSON.stringify(cases.map(c=>{const r=scaleCheck(c);return[r.scaled,r.cause]})))"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    for (name, _, scaled, cause), (g_scaled, g_cause) in zip(CASES, got):
        assert (g_scaled, g_cause) == (scaled, cause), name
