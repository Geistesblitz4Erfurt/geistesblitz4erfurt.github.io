"""Fetch Slovenian pronunciation audio files from Wiktionary / Wikimedia Commons.

For each surface form in the master DB's word_form table, query the MediaWiki API for an attached
Ogg/Mp3 pronunciation and download it to ``data/audio/words/``. Audio license info is retrieved via
the Commons ``imageinfo`` extmetadata endpoint; only CC-BY-SA 4.0 / CC0 / CC-BY-SA 3.0 compatible
files are kept.

Run:

    python -m build.ingest.wiktionary_audio_fetch --vocab build/_corpus_preview.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import requests

from build.ingest.schema import SOURCE_WIKTIONARY, open_db

API_WIKTIONARY = "https://en.wiktionary.org/w/api.php"
API_COMMONS = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "sl-pron/0.1 (https://example.local; build pipeline)"
COMPATIBLE_LICENSES = {
    "cc0",
    "cc-by-sa-4.0",
    "cc-by-sa-3.0",
    "cc-by-4.0",
    "cc-by-3.0",
}
AUDIO_DIR = Path("data/audio/words")
RATE_LIMIT_S = 0.5  # polite pacing


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _search_audio_for_word(session: requests.Session, word: str) -> list[dict]:
    """Find Commons files linked to the Wiktionary page for `word` that are audio."""
    resp = session.get(
        API_WIKTIONARY,
        params={
            "action": "query",
            "format": "json",
            "titles": word,
            "prop": "images",
            "imlimit": "50",
        },
        timeout=30,
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    results: list[dict] = []
    for page in pages.values():
        for image in page.get("images", []):
            name = image.get("title", "")
            if any(name.lower().endswith(ext) for ext in (".ogg", ".mp3", ".wav", ".flac", ".oga")):
                results.append({"title": name})
    return results


def _commons_imageinfo(session: requests.Session, title: str) -> dict | None:
    resp = session.get(
        API_COMMONS,
        params={
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
        },
        timeout=30,
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    for page in pages.values():
        infos = page.get("imageinfo", [])
        if infos:
            return infos[0]
    return None


def _license_compatible(info: dict) -> tuple[bool, str]:
    meta = info.get("extmetadata", {})
    short = (meta.get("LicenseShortName", {}) or {}).get("value", "").lower()
    canonical = (meta.get("License", {}) or {}).get("value", "").lower()
    for key in (short, canonical):
        for ok in COMPATIBLE_LICENSES:
            if ok in key.replace(" ", "-"):
                return True, key
    return False, short or canonical or "unknown"


def _is_slovene(info: dict, word: str) -> bool:
    meta = info.get("extmetadata", {})
    desc = (meta.get("ImageDescription", {}) or {}).get("value", "")
    title_blob = f"{desc} {info.get('descriptionurl', '')}".lower()
    # heuristics: slovene, sl, Lingua Libre speaker tag, or `/sl-` in title
    return any(kw in title_blob for kw in ("slovene", "slovenian", "sl-", "lingua libre"))


def _download(session: requests.Session, url: str, out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    resp = session.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    total = 0
    with out_path.open("wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            if not chunk:
                continue
            fh.write(chunk)
            total += len(chunk)
    return total


def fetch_for_vocabulary(vocab: list[str], db_path: Path) -> dict[str, int]:
    session = _session()
    conn = open_db(db_path)
    cur = conn.cursor()
    counts = {"checked": 0, "downloaded": 0, "skipped_license": 0, "no_audio": 0}
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for word in vocab:
        counts["checked"] += 1
        try:
            hits = _search_audio_for_word(session, word)
        except Exception as exc:
            print(f"[wiktionary] {word}: search failed: {exc}")
            continue
        if not hits:
            counts["no_audio"] += 1
            continue
        for hit in hits:
            title = hit["title"]
            info = _commons_imageinfo(session, title)
            if not info:
                continue
            ok, lic = _license_compatible(info)
            if not ok:
                counts["skipped_license"] += 1
                continue
            if not _is_slovene(info, word):
                continue
            url = info.get("url")
            if not url:
                continue
            ext = Path(url).suffix.lower().lstrip(".") or "ogg"
            safe = hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
            out_path = AUDIO_DIR / f"{word}_{safe}.{ext}"
            if out_path.exists():
                continue
            try:
                _download(session, url, out_path)
            except Exception as exc:
                print(f"[wiktionary] {word} download failed: {exc}")
                continue
            counts["downloaded"] += 1
            # find word_form row and attach
            cur.execute("SELECT id FROM word_form WHERE surface = ? LIMIT 1", (word,))
            row = cur.fetchone()
            if row:
                word_form_id = row[0]
                cur.execute(
                    """INSERT INTO audio_asset
                         (local_path, format, source, license, word_form_id)
                       VALUES (?, ?, 'wiktionary', ?, ?)""",
                    (str(out_path), ext, lic, word_form_id),
                )
                cur.execute(
                    "UPDATE word_form SET source_mask = source_mask | ? WHERE id = ?",
                    (SOURCE_WIKTIONARY, word_form_id),
                )
            conn.commit()
            time.sleep(RATE_LIMIT_S)
            break  # one audio per word is enough for MVP
        time.sleep(RATE_LIMIT_S)
    conn.close()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vocab", type=Path, default=Path("build/_corpus_preview.json"))
    ap.add_argument("--db", type=Path, default=Path("build/master.sqlite"))
    args = ap.parse_args()

    data = json.loads(args.vocab.read_text(encoding="utf-8"))
    vocab = data.get("vocab") or []
    if not vocab:
        print("[wiktionary] no vocab list found", file=sys.stderr)
        return 1
    print(f"[wiktionary] fetching audio for {len(vocab)} words")
    counts = fetch_for_vocabulary(vocab, args.db)
    print(f"[wiktionary] done: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
