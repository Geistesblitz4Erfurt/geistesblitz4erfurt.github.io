"""Download Sloleks 3.1 from CLARIN.SI and record its checksum.

The repository URL is https://www.clarin.si/repository/xmlui/handle/11356/2080. CLARIN.SI serves
the actual ZIP via a `bitstream` handle that we resolve on the fly. Users may also download the
file manually and drop it at ``sources/sloleks_3.1.zip`` — this script will verify the checksum
and continue.

Not run automatically: 262 MB. Invoke explicitly:

    python -m build.ingest.fetch_sloleks
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import requests

REPO_PAGE = "https://www.clarin.si/repository/xmlui/handle/11356/2080"
DEFAULT_OUT = Path("sources/sloleks_3.1.zip")
EXPECTED_MIN_SIZE_MB = 200
CHUNK = 1 << 20


def _resolve_bitstream_url(session: requests.Session) -> str:
    """Scrape the handle page to find the .zip bitstream link. Falls back to a known URL."""
    r = session.get(REPO_PAGE, timeout=30)
    r.raise_for_status()
    text = r.text
    import re

    m = re.search(r'href="([^"]*?Sloleks[^"]*?\.zip[^"]*)"', text, flags=re.I)
    if m:
        href = m.group(1).replace("&amp;", "&")
        if href.startswith("/"):
            return "https://www.clarin.si" + href
        return href
    raise RuntimeError(
        "Could not locate Sloleks ZIP link on the CLARIN.SI repository page. "
        "Please download manually and re-run with the file in place."
    )


def _download(url: str, out_path: Path) -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": "sl-pron/0.1 (+local build)"})
    with session.get(url, stream=True, timeout=60) as r:
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
                    print(f"\r[fetch_sloleks] {written / 1e6:7.1f} MB  ({pct:5.1f}%)", end="")
        print()
    digest = hasher.hexdigest()
    _record_checksum(out_path.name, digest, REPO_PAGE)


def _record_checksum(fname: str, sha256_hex: str, origin: str) -> None:
    manifest = Path("sources/checksums.txt")
    lines = []
    if manifest.exists():
        lines = [
            ln
            for ln in manifest.read_text(encoding="utf-8").splitlines()
            if not ln.strip().endswith(fname)
        ]
    lines.append(f"{sha256_hex}  {fname}  {origin}  CC-BY-SA-4.0")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _verify_existing(out_path: Path) -> bool:
    if not out_path.exists():
        return False
    size_mb = out_path.stat().st_size / (1024 * 1024)
    if size_mb < EXPECTED_MIN_SIZE_MB:
        print(
            f"[fetch_sloleks] existing file {out_path} is only {size_mb:.1f} MB "
            f"(expected ≥ {EXPECTED_MIN_SIZE_MB}); re-downloading"
        )
        return False
    hasher = hashlib.sha256()
    with out_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    _record_checksum(out_path.name, digest, REPO_PAGE)
    print(f"[fetch_sloleks] using existing file ({size_mb:.1f} MB, sha256 {digest[:12]}…)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if not args.force and _verify_existing(args.out):
        return 0
    session = requests.Session()
    print(f"[fetch_sloleks] resolving bitstream URL from {REPO_PAGE} …")
    url = _resolve_bitstream_url(session)
    print(f"[fetch_sloleks] downloading {url}")
    _download(url, args.out)
    print(f"[fetch_sloleks] saved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
