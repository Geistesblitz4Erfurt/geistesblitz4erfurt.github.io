"""Download per-sentence audio clips referenced in UD_Slovenian-SST metadata.

Each UD-SST sentence carries a ``# sound_url = ...`` comment pointing at either GOS 2
(``/project/gos20/...``) or ARTUR (``/project/iriss/...``) per-sentence mp3 files hosted by
Jožef Stefan Institute at ``nl.ijs.si``. HEAD requests return ``200 OK`` anonymously, so we
can mirror them.

**Licensing:** treat as **validation-only**. The underlying GOS 2 / ARTUR audio is under
restricted CLARIN licences; our downloaded copies are used only for build-time cross-checks
(acoustic alignment, duration validation, prosody ground-truth) and are never exported to
``/data``.

Outputs::

    sources/udsst_audio/
        gos/Gos<nnn>/Gos<nnn>.s<nnn>.mp3
        artur/Artur-P-G<nnn>-P<nnn>.s<nn>-s<nn>.mp3
    sources/udsst_audio/manifest.tsv        sent_id, source, local_path, text, sound_url
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
UDSST_DIR = REPO_ROOT / "sources" / "ud_sst"
OUT_DIR = REPO_ROOT / "sources" / "udsst_audio"
MANIFEST_PATH = OUT_DIR / "manifest.tsv"
CHECKSUMS = REPO_ROOT / "sources" / "checksums.txt"
USER_AGENT = "sl-pron/0.1 research build (contact: greenhartunicycle@gmail.com)"
RATE_LIMIT_S = 0.4


def _iter_sentences():
    url_re = re.compile(r"sound_url\s*=\s*(\S+)")
    text_re = re.compile(r"text\s*=\s*(.*)")
    sid_re = re.compile(r"sent_id\s*=\s*(\S+)")
    for p in sorted(UDSST_DIR.glob("*.conllu")):
        cur = {"sent_id": None, "text": None, "sound_url": None, "split": p.stem.split("-")[-1]}
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.startswith("#"):
                if ln == "" and cur["sent_id"]:
                    yield cur
                    cur = {"sent_id": None, "text": None, "sound_url": None, "split": p.stem.split("-")[-1]}
                continue
            m = sid_re.search(ln)
            if m: cur["sent_id"] = m.group(1)
            m = url_re.search(ln)
            if m: cur["sound_url"] = m.group(1)
            m = text_re.search(ln)
            if m: cur["text"] = m.group(1).strip()
        if cur["sent_id"]:
            yield cur


def _target_path(url: str) -> Path:
    parts = urlparse(url).path.lstrip("/").split("/")
    if "gos20" in parts:
        base = OUT_DIR / "gos" / parts[-2] / parts[-1]
    elif "iriss" in parts:
        base = OUT_DIR / "artur" / parts[-1]
    else:
        h = hashlib.sha1(url.encode()).hexdigest()[:12]
        base = OUT_DIR / "other" / f"{h}_{parts[-1]}"
    return base


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


def run(limit: int | None) -> dict[str, int]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    counts = {"seen": 0, "downloaded": 0, "skipped_existing": 0, "failed": 0}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_fh = MANIFEST_PATH.open("w", encoding="utf-8")
    manifest_fh.write("sent_id\tsplit\tsource\tlocal_path\ttext\tsound_url\n")
    n = 0
    for sent in _iter_sentences():
        if not sent["sound_url"]:
            continue
        counts["seen"] += 1
        n += 1
        if limit and n > limit:
            break
        url = sent["sound_url"]
        out = _target_path(url)
        source = "gos" if "/gos20/" in url else "artur" if "/iriss/" in url else "other"
        if out.exists() and out.stat().st_size > 0:
            counts["skipped_existing"] += 1
        else:
            try:
                _download(session, url, out)
                counts["downloaded"] += 1
            except Exception as exc:
                counts["failed"] += 1
                if counts["failed"] <= 5:
                    print(f"[udsst] dl fail {url}: {exc}")
                continue
            if counts["downloaded"] % 100 == 0:
                print(f"[udsst] downloaded={counts['downloaded']} failed={counts['failed']}")
            time.sleep(RATE_LIMIT_S)
        rel = out.relative_to(REPO_ROOT).as_posix()
        text = (sent["text"] or "").replace("\t", " ").replace("\n", " ")
        manifest_fh.write(f"{sent['sent_id']}\t{sent['split']}\t{source}\t{rel}\t{text}\t{url}\n")
    manifest_fh.close()
    # checksum line
    line = (
        "SNAPSHOT  sources/udsst_audio  "
        "https://nl.ijs.si/project/{gos20,iriss}/...  VALIDATION_ONLY (GOS2/ARTUR restricted)"
    )
    existing = CHECKSUMS.read_text(encoding="utf-8") if CHECKSUMS.exists() else ""
    kept = [ln for ln in existing.splitlines() if "udsst_audio" not in ln]
    kept.append(line)
    CHECKSUMS.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    counts = run(args.limit)
    print(f"[udsst] done: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
