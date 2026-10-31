"""Static UI regression tests for the compact H3 Studio layout.

No Mac, H3cApp, macmon, web browser, or node dependency is required.
When node is available we additionally validate the inline JavaScript syntax.
"""
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess

import pytest

UI = Path(__file__).resolve().parent.parent / "static" / "index.html"


class IDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        val = dict(attrs).get("id")
        if val:
            self.ids.append(val)


def test_telemetry_sits_in_one_header_not_generation_content():
    s = UI.read_text()
    header = s[s.index('<header class="topbar">'):s.index("</header>")]
    for key in (
        "headerMetrics", "gpuPct", "cpuPct", "ramPct", "cpuTemp",
        "gpuTemp", "systemPower", "cpuPower", "gpuPower", "anePower",
        "ramDetail", "h3pill", "sys", "theme", "logout",
    ):
        assert f'id="{key}"' in header, key
    assert '<div class="stats"' not in s
    assert s.index("</header>") < s.index('class="workspace-nav"') < s.index("<main>")
    assert "conic-gradient" in s and "ring.style.setProperty('--pct'" in s


def test_ui_retains_creation_and_queue_controls():
    s = UI.read_text()
    parsed = IDs()
    parsed.feed(s)
    assert len(parsed.ids) == len(set(parsed.ids)), "duplicate HTML element ID"
    for key in (
        "login", "loginBtn", "pw", "logout", "tab-gen", "tab-jobs", "tab-lib",
        "models", "cmode", "prompt", "shape", "size", "steps", "seed",
        "speed", "seconds", "fastAttention", "go", "ab", "active",
        "ended", "libBody", "dlg", "vid", "vid2",
    ):
        assert key in parsed.ids, key
    assert s.index('id="gpuPct"') < s.index("</header>") < s.index('id="models"')


def test_theme_is_browser_persistent_and_mobile_metrics_are_compact():
    s = UI.read_text()
    assert "localStorage.getItem('h3studio-theme')" in s
    assert "localStorage.setItem('h3studio-theme'" in s
    assert ":root[data-theme=\"dark\"]" in s
    assert "@media(max-width:720px)" in s
    assert ".head-metrics::-webkit-scrollbar{display:none}" in s


def test_javascript_syntax_when_node_available():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is optional; parse script in a browser")
    source = UI.read_text()
    script = source[source.rindex("<script>") + len("<script>"): source.rindex("</script>")]
    checked = subprocess.run(
        [node, "--check"], input=script, capture_output=True, text=True, timeout=5,
    )
    assert checked.returncode == 0, checked.stderr
