"""Foldable viewport regression checks without requiring H3cApp or a browser."""
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text()


def test_foldable_expanded_layout_uses_full_width():
    assert "Foldable inner screens and medium touch tablets" in HTML
    assert ".workspace-shell {" in HTML
    assert "width:100%;max-width:none;" in HTML
    assert "(min-width:600px) and (max-width:839px)" in HTML
    assert "(min-width:840px) and (max-width:1350px)" in HTML
    assert "(min-width:1351px) and (pointer:coarse)" in HTML
    assert "grid-template-columns:minmax(0,0.92fr) minmax(0,1.08fr)" in HTML
    assert "Unfolded portrait / near-square inner displays" in HTML
    assert "(orientation:portrait)" in HTML
    assert "#tab-gen {display:block}" in HTML
    assert "#tab-gen .models {" in HTML
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in HTML
    assert "#tab-gen .row {grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}" in HTML
    assert "#tab-gen textarea {min-height:clamp(150px,18vh,220px)" in HTML
    assert "#tab-gen #go {min-height:54px;font-size:16px}" in HTML
    assert "(orientation:landscape)" in HTML


def test_foldable_form_keeps_all_original_controls():
    for ident in ("models", "cmode", "kind", "ff", "lf", "prompt", "shape",
                  "size", "seconds", "steps", "seed", "speed",
                  "fastAttention", "go", "ab"):
        assert f'id="{ident}"' in HTML, ident
    assert "#tab-gen>.workspace-heading {grid-column:1/-1}" in HTML
    assert "#tab-gen .models {grid-template-columns:minmax(0,1fr)}" in HTML
    assert "#tab-gen .row {grid-template-columns:repeat(2,minmax(0,1fr))" in HTML


def test_folded_mobile_remains_compact_and_touch_targets_are_readable():
    assert "@media(max-width:720px)" in HTML
    assert ".models{grid-template-columns:1fr" in HTML
    assert ".workspace-nav button" in HTML
    assert "min-height:44px" in HTML
    assert ".head-metrics::-webkit-scrollbar {display:none}" in HTML
    assert "overscroll-behavior-x:contain" in HTML


def test_no_simulated_jobs_or_model_changes():
    assert "modelGone(j)" in HTML
    assert "boot().then(loadModels)" in HTML
    assert "beforeinstallprompt" in HTML
