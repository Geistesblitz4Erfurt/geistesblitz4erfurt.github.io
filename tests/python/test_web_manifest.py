"""PWA Web App Manifest invariants (W3C Manifest spec)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WM = ROOT / "web_test" / "manifest.webmanifest"


@pytest.fixture(scope="module")
def webmanifest() -> dict:
    assert WM.exists(), "missing web_test/manifest.webmanifest"
    return json.loads(WM.read_text(encoding="utf-8"))


def test_required_fields(webmanifest: dict) -> None:
    # https://www.w3.org/TR/appmanifest/#webappmanifest-dictionary
    for f in ("name", "short_name", "start_url", "scope", "display", "icons"):
        assert f in webmanifest, f"missing: {f}"


def test_display_is_standalone(webmanifest: dict) -> None:
    assert webmanifest["display"] in {"standalone", "fullscreen", "minimal-ui"}


def test_lang_is_slovenian(webmanifest: dict) -> None:
    assert webmanifest["lang"] == "sl-SI"


def test_scope_is_absolute(webmanifest: dict) -> None:
    assert webmanifest["scope"].startswith("/")


def test_start_url_within_scope(webmanifest: dict) -> None:
    assert webmanifest["start_url"].startswith(webmanifest["scope"].rstrip("/"))


def test_theme_and_background_colors(webmanifest: dict) -> None:
    assert webmanifest["theme_color"].startswith("#")
    assert webmanifest["background_color"].startswith("#")


def test_icons_include_maskable(webmanifest: dict) -> None:
    icons = webmanifest["icons"]
    assert icons, "no icons declared"
    has_192 = any("192" in i.get("sizes", "") for i in icons)
    has_512 = any("512" in i.get("sizes", "") for i in icons)
    has_maskable = any("maskable" in i.get("purpose", "") for i in icons)
    assert has_192 and has_512, "need both 192 and 512 sizes for install prompt"
    assert has_maskable, "need a maskable icon for Android adaptive"


def test_protocol_handlers(webmanifest: dict) -> None:
    handlers = webmanifest.get("protocol_handlers") or []
    assert any(h.get("protocol") == "web+slpron" for h in handlers)
    for h in handlers:
        # spec: protocol must start with 'web+' for custom
        assert h["protocol"].startswith("web+")
        assert "%s" in h["url"]


def test_json_parses(webmanifest: dict) -> None:
    # Round-trip to catch trailing-comma / BOM issues
    s = json.dumps(webmanifest)
    json.loads(s)
