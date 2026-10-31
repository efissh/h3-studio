"""Static installability regressions: no browser, H3 engine or GPU needed."""
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"


def test_manifest_has_mobile_installation_requirements():
    data = json.loads((STATIC / "manifest.webmanifest").read_text())
    assert data["id"] == "/" and data["start_url"] == "/" and data["scope"] == "/"
    assert data["display"] == "standalone"
    assert data["prefer_related_applications"] is False
    assert data["name"] and data["short_name"]
    sizes = {v["sizes"]: v for v in data["icons"]}
    assert {"192x192", "512x512"} <= set(sizes)
    for size, icon in sizes.items():
        assert icon["src"] == f"/pwa/icon-{size.split('x')[0]}.png"
        assert icon["type"] == "image/png"
        assert "maskable" in icon["purpose"]


def test_png_icons_are_real_correctly_sized_images():
    for dimension in (180, 192, 512):
        content = (STATIC / f"icon-{dimension}.png").read_bytes()
        assert content.startswith(b"\x89PNG\r\n\x1a\n")      # the real PNG signature, not backslash text
        assert content[12:16] == b"IHDR"
        assert struct.unpack(">II", content[16:24]) == (dimension, dimension)
        assert content.endswith(b"IEND\xaeB\x60\x82")
        assert len(content) > 500
        assert b"\\x89" not in content[:16]                      # guards against a double-escaped literal creeping back


def test_frontend_includes_desktop_and_mobile_install_paths():
    ui = (STATIC / "index.html").read_text()
    for attr in ('rel="manifest"', 'rel="apple-touch-icon"', 'apple-mobile-web-app-capable',
                 'id="installBtn"', "beforeinstallprompt", "display-mode: standalone",
                 "appinstalled", 'id="installDlg"'):
        assert attr in ui
    assert "添加到主屏幕" in ui
    assert "电脑 Chrome / Edge" in ui
    assert 'title="在电脑或手机上安装 H3 Studio"' in ui
    assert ".install-btn{display:inline-flex" in ui
    assert ".install-btn{display:none}" not in ui
    assert "安装网页为应用" in ui
    assert "appinstalled" in ui
    assert "HTTPS" in ui
    assert "navigator.serviceWorker.register" not in ui


def test_public_assets_are_strictly_whitelisted_and_private_media_unchanged():
    source = (ROOT / "app" / "main.py").read_text()
    assert '@app.get("/manifest.webmanifest", include_in_schema=False)' in source
    assert '@app.get("/pwa/icon-{size}.png", include_in_schema=False)' in source
    assert "size not in (180, 192, 512)" in source
    assert 'media_type="application/manifest+json"' in source
    assert 'media_type="image/png"' in source
    assert '@app.get("/api/jobs/{jid}/video", dependencies=[Depends(authed)])' in source
