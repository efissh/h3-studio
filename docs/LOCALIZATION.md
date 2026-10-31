# Localization

The user interface and the server's user-facing messages are currently **Chinese**. Code, comments, docs and the API are English. This page is the map for translating or adding a language.

## Where the text lives
| File | What |
|---|---|
| `static/index.html` | all UI text: static HTML, and JavaScript template strings (search for CJK characters: `grep -nP '[\x{4e00}-\x{9fff}]' static/index.html`) |
| `app/main.py` | HTTP error details, job notes/errors/stage names that appear in the UI |
| `app/models.py` | mode labels and notes, error messages |
| `static/manifest.webmanifest` | app description |

There are about 220 Chinese runs in the HTML and 120 in the Python files.

## Minimal approach (recommended for a fork)
Translate in place. With Claude Code, for example:

> Translate every user-visible Chinese string in `static/index.html`, `app/main.py`, `app/models.py` and `static/manifest.webmanifest` to English. Keep all code, ids, class names and JSON keys unchanged. Then run `.venv/bin/python -m pytest -q` and fix any test that asserts on a Chinese string.

Some tests assert on specific UI strings (for example `tests/test_pwa.py`, `tests/test_ui_design.py`, `tests/test_foldable_layout.py`); update them together with the text.

## A real multi-language build
If you want several languages in one build: add a `const T = {zh: {...}, en: {...}}` dictionary and a `t(key)` helper in `index.html`, replace literals with `t('…')` / `data-i18n` attributes, and return error *codes* from the server (the UI already shows `detail` strings verbatim) so the browser can translate them. Contributions welcome: please keep Chinese as a complete language.
