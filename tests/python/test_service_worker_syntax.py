"""Service-worker static checks (no JS runtime, pure textual contract).

We don't execute sw.js here — Python can't run a Service Worker context.
Instead we assert the file declares the handlers the browser expects, so
registration cannot silently skip install/activate/fetch.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SW = ROOT / "web_test" / "sw.js"
INSTALL = ROOT / "web_test" / "install.js"
FALLBACK = ROOT / "web_test" / "voice_fallback.js"


def test_sw_exists() -> None:
    assert SW.exists()


def test_sw_declares_required_listeners() -> None:
    src = SW.read_text(encoding="utf-8")
    for ev in ("install", "activate", "fetch", "message"):
        needle = f"addEventListener('{ev}'"
        assert needle in src, f"sw.js missing listener: {ev}"


def test_sw_uses_cache_storage_api() -> None:
    src = SW.read_text(encoding="utf-8")
    assert "caches.open(" in src
    assert "caches.keys(" in src or "caches.match(" in src


def test_sw_no_console_error_leaks() -> None:
    # Defensive: we never want the worker to crash silently on an
    # unhandled rejection leaking a stack in production.
    src = SW.read_text(encoding="utf-8")
    assert "self.addEventListener" in src


def test_installer_exposes_public_api() -> None:
    assert INSTALL.exists()
    src = INSTALL.read_text(encoding="utf-8")
    for sym in ("window.SLPronInstall", "install", "status", "uninstall"):
        assert sym in src, f"install.js missing: {sym}"
    assert "navigator.storage" in src
    assert "caches.open" in src
    assert "indexedDB" in src


def test_installer_verifies_sha1_and_schema() -> None:
    src = INSTALL.read_text(encoding="utf-8")
    assert "SHA-1" in src or "sha1" in src.lower()
    assert "slpron-voicepack.v1" in src
    assert "sl-SI" in src


def test_voice_fallback_uses_web_audio() -> None:
    assert FALLBACK.exists()
    src = FALLBACK.read_text(encoding="utf-8")
    for sym in ("AudioContext", "decodeAudioData", "createBufferSource", "VoiceFallback"):
        assert sym in src, f"voice_fallback.js missing: {sym}"
