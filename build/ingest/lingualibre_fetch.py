"""Fetch native Slovenian pronunciation audio from Wikimedia Commons Lingua Libre.

Lingua Libre is a Wikimedia project that records native-speaker pronunciations and uploads them
under CC-BY-SA 4.0. All Slovenian recordings land in the Commons category
``Category:Lingua Libre pronunciation-sln`` (ISO 639-3 code ``sln`` = Slovenian).

Strategy:

    1. Enumerate category members via Commons API (``action=query&list=categorymembers``).
    2. For each file, fetch ``imageinfo`` (url + extmetadata) to extract the spoken word and
       license.
    3. Download the OGG file to ``data/audio/words/lingualibre/`` using a name-hash for safety.
    4. Record the asset row in the master DB ``audio_asset`` table and flip the
       ``SOURCE_LINGUALIBRE`` bit on the corresponding ``word_form`` if a surface match exists.

Run::

    python -m build.ingest.lingualibre_fetch --limit 5000
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from pathlib import Path

import requests

from build.ingest.schema import SOURCE_LINGUALIBRE, open_db

API_COMMONS = "https://commons.wikimedia.org/w/api.php"
# Slovene ISO 639-3 = slv, Wikidata Q9063. Category iteration returns nothing for us; use
# filename search which reliably matches every LL-Q9063 upload.
FILENAME_QUERY = 'intitle:"LL-Q9063"'
USER_AGENT = "sl-pron/0.1 research build (contact: greenhartunicycle@gmail.com)"
AUDIO_DIR = Path("data/audio/words/lingualibre")
COMPATIBLE_LICENSES = {
    "cc0",
    "cc-by-sa-4.0",
    "cc-by-sa-3.0",
    "cc-by-4.0",
    "cc-by-3.0",
}
# Wikimedia enforces strict rate limits on upload.wikimedia.org. 1.5s between downloads is safe.
RATE_LIMIT_S = 1.5

# Lingua Libre filename pattern:  "LL-Q9063 (slv)-<speaker>-<word>.wav"  (older: .ogg)
# Newer LL filenames embed the word after the last dash-word segment; we use a regex.
FILENAME_RE = re.compile(
    r"LL-Q\d+\s*\(\s*(?:slv|sln)\s*\)-[^-]+-(?P<word>.+?)\.(?:wav|ogg|oga|mp3)",
    re.IGNORECASE,
)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _iter_category_members(session: requests.Session, limit: int | None):
    cont: dict = {}
    n = 0
    while True:
        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": FILENAME_QUERY,
            "srlimit": "50",
            "srnamespace": "6",  # File namespace
        }
        params.update(cont)
        r = session.get(API_COMMONS, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        for m in data.get("query", {}).get("search", []):
            yield m["title"]
            n += 1
            if limit and n >= limit:
                return
        cont = data.get("continue") or {}
        if not cont:
            return


def _imageinfo(session: requests.Session, title: str) -> dict | None:
    r = session.get(
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
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", {})
    for p in pages.values():
        infos = p.get("imageinfo", [])
        if infos:
            return infos[0]
    return None


def _license_compatible(info: dict) -> tuple[bool, str]:
    meta = info.get("extmetadata", {})
    short = (meta.get("LicenseShortName", {}) or {}).get("value", "").lower()
    canonical = (meta.get("License", {}) or {}).get("value", "").lower()
    for key in (short, canonical):
        norm = key.replace(" ", "-")
        for ok in COMPATIBLE_LICENSES:
            if ok in norm:
                return True, key
    return False, short or canonical or "unknown"


def _extract_word(title: str) -> str | None:
    base = title.split(":", 1)[-1] if title.lower().startswith("file:") else title
    m = FILENAME_RE.match(base)
    if m:
        return m.group("word").strip().replace("_", " ")
    return None


def _download(session: requests.Session, url: str, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    r = session.get(url, stream=True, timeout=60)
    r.raise_for_status()
    total = 0
    with out.open("wb") as fh:
        for chunk in r.iter_content(chunk_size=1 << 16):
            if not chunk:
                continue
            fh.write(chunk)
            total += len(chunk)
    return total


def run(db_path: Path, limit: int | None) -> dict[str, int]:
    session = _session()
    conn = open_db(db_path)
    cur = conn.cursor()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    counts = {"seen": 0, "downloaded": 0, "license_skip": 0, "no_word": 0, "matched_form": 0}
    for title in _iter_category_members(session, limit):
        counts["seen"] += 1
        word = _extract_word(title)
        if not word:
            counts["no_word"] += 1
            continue
        try:
            info = _imageinfo(session, title)
        except Exception as exc:
            print(f"[ll] info failed {title}: {exc}")
            continue
        if not info:
            continue
        ok, lic = _license_compatible(info)
        if not ok:
            counts["license_skip"] += 1
            continue
        url = info.get("url")
        if not url:
            continue
        ext = Path(url).suffix.lower().lstrip(".") or "ogg"
        safe = hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
        out_path = AUDIO_DIR / f"{word}_{safe}.{ext}"
        if not out_path.exists():
            try:
                _download(session, url, out_path)
            except Exception as exc:
                print(f"[ll] dl failed {title}: {exc}")
                continue
            counts["downloaded"] += 1
        # attach to a matching surface form if any
        cur.execute("SELECT id FROM word_form WHERE surface = ? LIMIT 1", (word,))
        row = cur.fetchone()
        if row:
            word_form_id = row[0]
            cur.execute(
                """INSERT OR IGNORE INTO audio_asset
                     (local_path, format, source, license, word_form_id)
                   VALUES (?, ?, 'lingualibre', ?, ?)""",
                (str(out_path), ext, lic, word_form_id),
            )
            cur.execute(
                "UPDATE word_form SET source_mask = source_mask | ? WHERE id = ?",
                (SOURCE_LINGUALIBRE, word_form_id),
            )
            counts["matched_form"] += 1
        if counts["downloaded"] % 200 == 0 and counts["downloaded"]:
            conn.commit()
            print(f"[ll] downloaded={counts['downloaded']} matched={counts['matched_form']}")
        time.sleep(RATE_LIMIT_S)
    conn.commit()
    conn.close()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path("build/master.sqlite"))
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    counts = run(args.db, args.limit)
    print(f"[lingualibre] done: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
