"""Download ARTUR 1.0 speech corpus from CLARIN.SI.

ARTUR 1.0 is a large Slovenian read/spontaneous speech corpus distributed under CC-BY 4.0.
Landing page: https://www.clarin.si/repository/xmlui/handle/11356/1772. Bitstream ZIP links
are scraped live because CLARIN.SI can split large deposits across multiple bitstreams.

Invoke explicitly (total ~10–20 GB across parts):

    PYTHONIOENCODING=utf-8 python -m build.ingest.fetch_artur
"""
from __future__ import annotations

import argparse
import hashlib
import html
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote

import requests

REPO_PAGE = "https://www.clarin.si/repository/xmlui/handle/11356/1772"
OUT_DIR = Path("sources/artur")
LICENSE = "CC-BY-4.0"
CHUNK = 1 << 20  # 1 MB
EXPECTED_MIN_SIZE_MB = 100
CHECKSUMS = Path("sources/checksums.txt")

BITSTREAM_RE = re.compile(
    r'href="(/repository/xmlui/bitstream/handle/11356/1772/[^"]*?\.zip[^"]*)"',
    flags=re.I,
)


def _scrape_bitstream_urls(session: requests.Session) -> list[str]:
    r = session.get(REPO_PAGE, timeout=60)
    r.raise_for_status()
    hrefs = set()
    for m in BITSTREAM_RE.finditer(r.text):
        href = html.unescape(m.group(1)).replace("&amp;", "&")
        hrefs.add(urljoin("https://www.clarin.si", href))
    return sorted(hrefs)


def _filename_from_url(url: str) -> str:
    path = urlsplit(url).path
    name = unquote(path.rsplit("/", 1)[-1])
    return name


def _append_checksum(fname: str, sha256_hex: str, origin: str, license_tag: str) -> None:
    CHECKSUMS.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if CHECKSUMS.exists():
        existing = CHECKSUMS.read_text(encoding="utf-8")
        # Skip if this exact line is already present
        needle = f"  {fname}  "
        for ln in existing.splitlines():
            if ln.startswith(sha256_hex) and needle in ln:
                return
    line = f"{sha256_hex}  {fname}  {origin}  {license_tag}\n"
    sep = "" if existing.endswith("\n") or not existing else "\n"
    with CHECKSUMS.open("a", encoding="utf-8") as fh:
        fh.write(sep + line)


def _hash_existing(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, out_path: Path) -> str:
    session = requests.Session()
    session.headers.update({"User-Agent": "sl-pron/0.1 (+local build)"})
    with session.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        written = 0
        with out_path.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=CHUNK):
                if not chunk:
                    continue
                fh.write(chunk)
                hasher.update(chunk)
                written += len(chunk)
                if total:
                    pct = 100 * written / total
                    print(
                        f"\r[fetch_artur] {out_path.name}: "
                        f"{written / 1e6:8.1f} MB  ({pct:5.1f}%)",
                        end="",
                        flush=True,
                    )
                else:
                    print(
                        f"\r[fetch_artur] {out_path.name}: {written / 1e6:8.1f} MB",
                        end="",
                        flush=True,
                    )
        print()
    return hasher.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": "sl-pron/0.1 (+local build)"})

    print(f"[fetch_artur] scraping bitstream links from {REPO_PAGE}")
    try:
        urls = _scrape_bitstream_urls(session)
    except Exception as exc:
        print(f"[fetch_artur] ERROR: scrape failed: {exc}", file=sys.stderr)
        return 2
    if not urls:
        print(
            "[fetch_artur] ERROR: regex did not match any .zip bitstream URLs on the page. "
            "Page layout may have changed or requires authentication.",
            file=sys.stderr,
        )
        return 3
    print(f"[fetch_artur] found {len(urls)} bitstream ZIP(s):")
    for u in urls:
        print(f"  - {u}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    failures: list[tuple[str, str]] = []

    for url in urls:
        fname = _filename_from_url(url)
        out_path = args.out_dir / fname

        if not args.force and out_path.exists():
            size_mb = out_path.stat().st_size / (1024 * 1024)
            if size_mb >= EXPECTED_MIN_SIZE_MB:
                print(
                    f"[fetch_artur] skip {fname} (already {size_mb:.1f} MB); hashing for manifest"
                )
                digest = _hash_existing(out_path)
                _append_checksum(f"artur/{fname}", digest, REPO_PAGE, LICENSE)
                continue
            else:
                print(
                    f"[fetch_artur] existing {fname} only {size_mb:.1f} MB, re-downloading"
                )

        print(f"[fetch_artur] downloading {url} -> {out_path}")
        try:
            digest = _download(url, out_path)
        except Exception as exc:
            print(f"[fetch_artur] FAILED {fname}: {exc}", file=sys.stderr)
            failures.append((fname, str(exc)))
            continue
        _append_checksum(f"artur/{fname}", digest, REPO_PAGE, LICENSE)
        print(f"[fetch_artur] saved {out_path} sha256={digest[:12]}…")

    if failures:
        print(f"[fetch_artur] {len(failures)} failure(s):", file=sys.stderr)
        for fname, exc in failures:
            print(f"  - {fname}: {exc}", file=sys.stderr)
        return 1
    print("[fetch_artur] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
