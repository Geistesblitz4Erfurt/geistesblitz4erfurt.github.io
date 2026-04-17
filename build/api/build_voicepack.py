"""Build the installable Voice-Pack manifest.

The Voice-Pack is a machine-readable bundle the browser can download once and
then use offline. It is served as a collection of static files on GitHub Pages:

    /data/api/voicepack/manifest.json      ← this file (index)
    /data/api/phrasebook.json.gz            ← included
    /data/api/phrasebook_index.json         ← included
    /data/audio/words/<file>.wav|ogg|oga    ← included (per-word samples)

The manifest lists every asset with its size, sha1, content-type, and a
client-side bucket:

    { "role": "shell",      ... }  cached at SW install
    { "role": "phrasebook", ... }  cached by install.js, required
    { "role": "audio",      ... }  cached by install.js, per-item
    { "role": "ipa_index",  ... }  SL surface → IPA compressed JSON

Tight invariants (validated by tests):

    * every listed file resolves relative to site root
    * total_size_bytes == sum(asset.size_bytes)
    * every asset has sha1 == hashlib.sha1(file_bytes).hexdigest()
    * manifest.lang == "sl-SI"
    * manifest.license == "CC-BY-SA-4.0"
    * schema == "slpron-voicepack.v1"

Run::

    python -m build.api.build_voicepack
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
API = DATA / "api"
AUDIO_DIRS = [
    DATA / "audio" / "words" / "lingualibre",
    DATA / "audio" / "words",
]
OUT_DIR = API / "voicepack"
MANIFEST_OUT = OUT_DIR / "manifest.json"
IPA_INDEX_OUT = OUT_DIR / "ipa_index.json.gz"
DB_PATH = ROOT / "build" / "master.sqlite"

PIPELINE_VERSION = "1.0.0"
SCHEMA = "slpron-voicepack.v1"
LICENSE = "CC-BY-SA-4.0"
LANG = "sl-SI"


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _content_type(p: Path) -> str:
    suf = p.suffix.lower()
    return {
        ".json": "application/json; charset=utf-8",
        ".gz":   "application/json; charset=utf-8",  # we gzip JSON only
        ".wav":  "audio/wav",
        ".ogg":  "audio/ogg",
        ".oga":  "audio/ogg",
        ".mp3":  "audio/mpeg",
        ".webmanifest": "application/manifest+json",
        ".js":   "application/javascript; charset=utf-8",
        ".html": "text/html; charset=utf-8",
    }.get(suf, "application/octet-stream")


def _encoding(p: Path) -> str | None:
    return "gzip" if p.suffix.lower() == ".gz" else None


def _asset(path: Path, role: str, *, key: str | None = None) -> dict[str, Any]:
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    size = path.stat().st_size
    return {
        "role": role,
        "key": key or path.stem,
        "url": "/" + rel,                 # site-root relative, identical on GH Pages
        "size_bytes": size,
        "sha1": _sha1(path),
        "content_type": _content_type(path),
        "content_encoding": _encoding(path),
    }


def _build_ipa_index() -> dict[str, str]:
    """Flat {surface_lower: ipa_post_sandhi_or_sloleks} index for fallback TTS.

    The client joins tokens by looking up each surface word. Uses Sloleks'
    highest-quality IPA; lower-cased keys for case-insensitive match.
    """
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA query_only = 1;")
    cur = conn.cursor()
    cur.execute(
        "SELECT LOWER(surface), ipa FROM word_form "
        "WHERE ipa IS NOT NULL "
        "GROUP BY LOWER(surface) "
        "HAVING quality_score = MAX(quality_score) "
        "LIMIT 200000"
    )
    idx: dict[str, str] = {}
    for surf, ipa in cur.fetchall():
        if surf and ipa and surf not in idx:
            idx[surf] = ipa
    conn.close()
    return idx


def _gather_audio() -> list[Path]:
    out: list[Path] = []
    seen_names: set[str] = set()
    for d in AUDIO_DIRS:
        if not d.exists():
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() not in {".wav", ".ogg", ".oga", ".mp3"}:
                continue
            key = p.name
            if key in seen_names:
                continue
            seen_names.add(key)
            out.append(p)
    return out


def build() -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Build + persist IPA index (so it can be listed as an asset).
    ipa_index = _build_ipa_index()
    body = json.dumps(ipa_index, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(IPA_INDEX_OUT, "wb", compresslevel=9) as f:
        f.write(body)

    # 2. Collect assets.
    assets: list[dict[str, Any]] = []

    phrasebook = API / "phrasebook.json.gz"
    if phrasebook.exists():
        assets.append({**_asset(phrasebook, "phrasebook", key="phrasebook"), "required": True})
    pb_index = API / "phrasebook_index.json"
    if pb_index.exists():
        assets.append({**_asset(pb_index, "phrasebook_index", key="phrasebook_index"), "required": True})
    assets.append({**_asset(IPA_INDEX_OUT, "ipa_index", key="ipa_index"), "required": True})

    for audio in _gather_audio():
        # audio key = filename stem before last _hash segment
        stem = audio.stem
        surface = stem.rsplit("_", 1)[0] if "_" in stem else stem
        assets.append({
            **_asset(audio, "audio", key=surface.lower()),
            "required": False,     # audio is incremental; Pack usable w/o it
            "surface_sl": surface,
        })

    total_size = sum(a["size_bytes"] for a in assets)
    sha1_map = hashlib.sha1()
    for a in assets:
        sha1_map.update((a["url"] + ":" + a["sha1"]).encode("utf-8"))
    bundle_sha1 = sha1_map.hexdigest()

    manifest = {
        "schema": SCHEMA,
        "name": "SL-Pron · Slovenian Voice-Pack",
        "short_name": "sl-pron",
        "version": PIPELINE_VERSION,
        "generated_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "lang": LANG,
        "license": LICENSE,
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "attribution": [
            "Sloleks 3.1 (CJVT, University of Ljubljana) — CC-BY-SA-4.0",
            "Lingua Libre / Wikimedia Commons — CC-BY-SA-4.0",
        ],
        "total_size_bytes": total_size,
        "asset_count": len(assets),
        "bundle_sha1": bundle_sha1,
        "assets": assets,
        "install": {
            "cache_name": f"sl-pron-voicepack-{PIPELINE_VERSION}",
            "storage_persist": True,              # navigator.storage.persist()
            "strategy": "cache-first",            # SW cache-first, network-fallback
            "min_quota_mb": 32,                    # soft warning threshold
        },
        "capabilities": {
            "web_speech_api": True,               # host browser's sl-SI voice (preferred)
            "fallback_concat_audio": True,        # Web-Audio stitching from samples
            "offline_after_install": True,
            "deep_link_scheme": "web+slpron",     # see ProtocolHandler spec
        },
        "endpoints": {
            "manifest":     "/data/api/voicepack/manifest.json",
            "install_page": "/install.html",
            "ping":         "/api/voicepack/ping",
        },
        "pipeline_version": PIPELINE_VERSION,
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    m = build()
    print(f"[voicepack] wrote {MANIFEST_OUT}")
    print(f"[voicepack] {m['asset_count']} assets, {m['total_size_bytes']/1024:.1f} kB total")
    print(f"[voicepack] bundle_sha1 = {m['bundle_sha1']}")
    if args.verbose:
        roles: dict[str, int] = {}
        for a in m["assets"]:
            roles[a["role"]] = roles.get(a["role"], 0) + 1
        print(f"[voicepack] roles: {roles}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
