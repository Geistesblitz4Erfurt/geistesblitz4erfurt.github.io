"""Voice-Pack manifest hard invariants.

Every byte listed in the manifest must exist on disk with the declared size
and sha1. Clients reject mismatches, so the build must never emit a drifted
manifest.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MF = ROOT / "data" / "api" / "voicepack" / "manifest.json"


def _build_if_missing() -> None:
    if MF.exists():
        return
    from build.api import build_voicepack
    build_voicepack.build()


@pytest.fixture(scope="module")
def manifest() -> dict:
    _build_if_missing()
    return json.loads(MF.read_text(encoding="utf-8"))


def test_schema(manifest: dict) -> None:
    assert manifest["schema"] == "slpron-voicepack.v1"


def test_lang_locked_to_slovenian(manifest: dict) -> None:
    assert manifest["lang"] == "sl-SI"


def test_license_is_cc_by_sa(manifest: dict) -> None:
    assert manifest["license"] == "CC-BY-SA-4.0"
    assert manifest["license_url"].startswith("https://creativecommons.org/")


def test_required_toplevel_fields(manifest: dict) -> None:
    for f in (
        "schema", "name", "short_name", "version", "generated_at",
        "lang", "license", "license_url", "attribution",
        "total_size_bytes", "asset_count", "bundle_sha1", "assets",
        "install", "capabilities", "endpoints", "pipeline_version",
    ):
        assert f in manifest, f"missing field: {f}"


def test_install_block(manifest: dict) -> None:
    inst = manifest["install"]
    assert inst["cache_name"].startswith("sl-pron-voicepack-")
    assert inst["storage_persist"] is True
    assert inst["strategy"] == "cache-first"
    assert inst["min_quota_mb"] >= 16


def test_capabilities(manifest: dict) -> None:
    cap = manifest["capabilities"]
    assert cap["web_speech_api"] is True
    assert cap["offline_after_install"] is True
    assert cap["deep_link_scheme"] == "web+slpron"


def test_endpoints(manifest: dict) -> None:
    ep = manifest["endpoints"]
    assert ep["manifest"] == "/data/api/voicepack/manifest.json"
    assert ep["install_page"] == "/install.html"


def test_asset_count_matches(manifest: dict) -> None:
    assert manifest["asset_count"] == len(manifest["assets"])


def test_total_size_matches(manifest: dict) -> None:
    summed = sum(a["size_bytes"] for a in manifest["assets"])
    assert manifest["total_size_bytes"] == summed


def test_at_least_three_required_assets(manifest: dict) -> None:
    required = [a for a in manifest["assets"] if a.get("required")]
    roles = {a["role"] for a in required}
    # phrasebook + phrasebook_index + ipa_index must all be required
    assert {"phrasebook", "phrasebook_index", "ipa_index"}.issubset(roles)


def test_every_url_site_root_relative(manifest: dict) -> None:
    for a in manifest["assets"]:
        assert a["url"].startswith("/"), f"url not site-root-relative: {a['url']}"
        assert "\\" not in a["url"], f"backslash in url: {a['url']}"
        assert ".." not in a["url"], f"traversal in url: {a['url']}"


def test_every_file_exists_and_sha1_matches(manifest: dict) -> None:
    failures = []
    for a in manifest["assets"]:
        p = ROOT / a["url"].lstrip("/")
        if not p.exists():
            failures.append(f"missing: {p}")
            continue
        size = p.stat().st_size
        if size != a["size_bytes"]:
            failures.append(f"size mismatch {p}: {size} != {a['size_bytes']}")
            continue
        h = hashlib.sha1()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        if h.hexdigest() != a["sha1"]:
            failures.append(f"sha1 mismatch {p}")
    assert not failures, "\n".join(failures)


def test_bundle_sha1_stable(manifest: dict) -> None:
    h = hashlib.sha1()
    for a in manifest["assets"]:
        h.update((a["url"] + ":" + a["sha1"]).encode("utf-8"))
    assert h.hexdigest() == manifest["bundle_sha1"]


def test_content_types_sane(manifest: dict) -> None:
    for a in manifest["assets"]:
        ct = a["content_type"]
        if a["role"] == "audio":
            assert ct.startswith("audio/"), f"{a['url']} → {ct}"
        elif a["role"] in {"phrasebook", "phrasebook_index", "ipa_index"}:
            assert "json" in ct, f"{a['url']} → {ct}"


def test_gzipped_assets_declare_encoding(manifest: dict) -> None:
    for a in manifest["assets"]:
        if a["url"].endswith(".gz"):
            assert a["content_encoding"] == "gzip", f"missing gzip encoding on {a['url']}"


def test_no_duplicate_urls(manifest: dict) -> None:
    urls = [a["url"] for a in manifest["assets"]]
    assert len(urls) == len(set(urls))
