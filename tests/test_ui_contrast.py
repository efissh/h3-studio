"""Dark-theme readability guardrails (no browser or hardware required).

The screenshot-driven contrast pass must remain readable at normal monitor
brightness in both explicit dark mode and system-auto dark mode.
"""
from pathlib import Path
import re

UI = (Path(__file__).resolve().parent.parent / "static" / "index.html").read_text()


def palette(selector: str) -> dict[str, str]:
    match = re.search(re.escape(selector) + r"\s*\{([^{}]+)\}", UI)
    assert match, f"Missing theme selector: {selector}"
    return dict(re.findall(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})", match.group(1)))


def linear_component(value: int) -> float:
    v = value / 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    raw = bytes.fromhex(color[1:])
    r, g, b = (linear_component(v) for v in raw)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_explicit_and_auto_dark_modes_use_identical_tokens():
    assert palette(':root[data-theme="dark"]') == palette(':root:not([data-theme="light"])')


def test_dark_theme_text_meets_wcag_aa_and_primary_exceeds_aaa():
    p = palette(':root[data-theme="dark"]')
    for foreground, background, minimum in (
        ("fg", "card", 7.0),
        ("fg", "control", 7.0),
        ("mut", "card", 7.0),
        ("mut-2", "card-alt", 4.5),
        ("mut-2", "control", 4.5),   # prompt placeholders
        ("mut-2", "bg", 4.5),        # header microcopy
        ("acc", "bg", 4.5),
    ):
        result = contrast(p[foreground], p[background])
        assert result >= minimum, f"{foreground}/{background}: {result:.2f}, need {minimum}"


def test_dark_input_control_boundaries_are_visible():
    p = palette(':root[data-theme="dark"]')
    for background in ("control", "card-alt"):
        assert contrast(p["field-line"], p[background]) >= 3.0
    assert "border:1px solid var(--field-line,var(--line))" in UI
    assert "textarea::placeholder,input::placeholder{color:var(--mut-2);opacity:1}" in UI


def test_header_and_model_typography_is_legible():
    assert ".metric-copy strong{\n  color:var(--fg);font-size:16px" in UI
    assert ".metric-copy small{\n  color:var(--mut-2);font-weight:730;font-size:10px" in UI
    assert ".mcard b{display:block;padding-right:17px;font-size:14px" in UI
    assert ".mcard .meta{display:block;margin:5px 0 11px;font-size:12px" in UI
    assert ".mcard.off{opacity:.79" in UI  # unavailable remains visibly distinct without washing text out
