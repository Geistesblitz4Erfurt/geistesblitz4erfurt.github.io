"""Download the Mozilla Common Voice Slovenian (``sl``) corpus.

Strategy (in order):
    1. Direct S3 tarball at
       ``https://mozilla-common-voice-datasets.s3.dualstack.us-west-2.amazonaws.com/
       cv-corpus-<VERSION>/cv-corpus-<VERSION>-sl.tar.gz``
       for the newest known versions. Mozilla usually puts these behind a signed URL
       fronted by an email gate, but older releases are occasionally public; we probe.
    2. Hugging Face mirror ``mozilla-foundation/common_voice_17_0`` via the
       ``datasets`` library in streaming mode (requires ``pip install datasets`` and
       acceptance of the dataset terms on the HF hub, which grants the
       default HF token read access).

Outputs under ``sources/common_voice/``:
    - ``clips/<client_hash>_<idx>.mp3``              -- individual audio clips (mp3)
    - ``manifest.tsv``                                -- TSV with columns
       ``client_id, path, sentence, up_votes, down_votes, age, gender, accents,
       locale, segment``
    - Appends sha256 of the manifest + license record to ``sources/checksums.txt``.

The script is idempotent: if ``sources/common_voice/clips/`` already contains clips,
no re-download is attempted.

Run:

    PYTHONIOENCODING=utf-8 python -m build.ingest.fetch_common_voice
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import requests

# Known CV release candidates, newest first. Probed in order.
_S3_BASE = (
    "https://mozilla-common-voice-datasets.s3.dualstack.us-west-2.amazonaws.com"
)
_CV_CANDIDATES = [
    # (version string, date string) -> URL path cv-corpus-<v>-<date>-sl.tar.gz
    ("21.0", "2025-03-14"),
    ("20.0", "2024-12-06"),
    ("19.0", "2024-09-13"),
    ("18.0", "2024-06-14"),
    ("17.0", "2024-03-15"),
    ("16.1", "2023-12-06"),
]
HF_DATASET = "mozilla-foundation/common_voice_17_0"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "sources" / "common_voice"
CLIPS_DIR = OUT_DIR / "clips"
MANIFEST_PATH = OUT_DIR / "manifest.tsv"
LOG_PATH = ROOT / "build" / "_cv.log"
CHECKSUMS_PATH = ROOT / "sources" / "checksums.txt"

MANIFEST_COLS = [
    "client_id",
    "path",
    "sentence",
    "up_votes",
    "down_votes",
    "age",
    "gender",
    "accents",
    "locale",
    "segment",
]

USER_AGENT = "sl-pron/0.1 (+common-voice ingest)"
CHUNK = 1 << 20


# ---------------------------------------------------------------------------
# logging helpers
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    line = f"[fetch_common_voice] {msg}"
    print(line, flush=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ---------------------------------------------------------------------------
# Direct S3 tarball path
# ---------------------------------------------------------------------------

def _probe_s3_url(session: requests.Session) -> str | None:
    """Return the first CV tarball URL that answers with 200 via HEAD."""
    for version, date in _CV_CANDIDATES:
        url = f"{_S3_BASE}/cv-corpus-{version}-{date}/cv-corpus-{version}-{date}-sl.tar.gz"
        try:
            r = session.head(url, allow_redirects=True, timeout=30)
        except requests.RequestException as exc:  # pragma: no cover - network
            _log(f"  probe {version}: network error {exc}")
            continue
        _log(f"  probe cv-{version}-{date}-sl.tar.gz -> HTTP {r.status_code}")
        if r.status_code == 200:
            return url
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_tarball(url: str, session: requests.Session) -> Path:
    tar_path = OUT_DIR / url.rsplit("/", 1)[-1]
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    _log(f"downloading tarball from {url}")
    with session.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        written = 0
        with tar_path.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=CHUNK):
                if not chunk:
                    continue
                fh.write(chunk)
                written += len(chunk)
                if total and written % (16 * CHUNK) < CHUNK:
                    pct = 100 * written / total
                    _log(f"  {written / 1e6:7.1f} MB ({pct:5.1f}%)")
    _log(f"saved tarball {tar_path} ({tar_path.stat().st_size / 1e6:.1f} MB)")
    return tar_path


def _extract_tarball(tar_path: Path) -> list[dict]:
    """Extract mp3 clips + TSV to OUT_DIR. Returns manifest rows (list of dicts)."""
    rows: list[dict] = []
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    # Pull validated.tsv (preferred) else train.tsv
    preferred = ["validated.tsv", "train.tsv", "other.tsv"]
    _log(f"extracting {tar_path.name}")
    with tarfile.open(tar_path, "r:gz") as tf:
        members = tf.getmembers()
        # Find a suitable manifest tsv
        tsv_member = None
        for name in preferred:
            for m in members:
                if m.name.endswith(f"/sl/{name}"):
                    tsv_member = m
                    break
            if tsv_member is not None:
                break
        if tsv_member is None:
            raise RuntimeError("No validated/train/other TSV found in tarball")
        _log(f"using manifest {tsv_member.name}")
        tsv_fh = tf.extractfile(tsv_member)
        assert tsv_fh is not None
        raw = tsv_fh.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(raw), delimiter="\t")
        keep_paths: set[str] = set()
        for rec in reader:
            if (rec.get("locale") or "sl").lower() != "sl":
                continue
            row = {k: (rec.get(k) or "") for k in MANIFEST_COLS}
            row["locale"] = row.get("locale") or "sl"
            rows.append(row)
            keep_paths.add(row["path"])
        _log(f"  manifest rows: {len(rows)}")
        # Extract referenced clips
        for m in members:
            base = m.name.rsplit("/", 1)[-1]
            if base in keep_paths and m.isfile():
                fh = tf.extractfile(m)
                if fh is None:
                    continue
                out = CLIPS_DIR / base
                out.write_bytes(fh.read())
    _log(f"extracted {sum(1 for _ in CLIPS_DIR.glob('*.mp3'))} mp3 clips")
    return rows


# ---------------------------------------------------------------------------
# HuggingFace fallback
# ---------------------------------------------------------------------------

def _hf_fallback() -> list[dict]:
    try:
        from datasets import load_dataset  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            f"`datasets` library not installed ({exc}); "
            "run `pip install datasets` and retry"
        )
    rows: list[dict] = []
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    _log(f"using Hugging Face mirror {HF_DATASET} (streaming)")
    # validated is ideal; fall back to train/test if missing
    for split in ("validated", "train", "test"):
        try:
            ds = load_dataset(
                HF_DATASET,
                "sl",
                split=split,
                streaming=True,
                trust_remote_code=True,
            )
        except Exception as exc:
            _log(f"  split '{split}' unavailable: {exc}")
            continue
        count = 0
        for rec in ds:
            # audio field = {'path': ..., 'bytes': ...} in streaming mode
            audio = rec.get("audio") or {}
            raw_bytes = audio.get("bytes")
            path = rec.get("path") or audio.get("path") or ""
            if not path:
                continue
            base = path.rsplit("/", 1)[-1]
            if not base.endswith(".mp3"):
                base = base + ".mp3" if "." not in base else base
            out = CLIPS_DIR / base
            if raw_bytes and not out.exists():
                out.write_bytes(raw_bytes)
            elif audio.get("array") is not None and not out.exists():
                # array+sr case -- re-encode to wav
                try:
                    import soundfile as sf  # type: ignore
                    out_wav = out.with_suffix(".wav")
                    sf.write(out_wav, audio["array"], int(audio.get("sampling_rate", 16000)))
                    base = out_wav.name
                except Exception:
                    continue
            row = {
                "client_id": rec.get("client_id", ""),
                "path": base,
                "sentence": rec.get("sentence", ""),
                "up_votes": rec.get("up_votes", 0),
                "down_votes": rec.get("down_votes", 0),
                "age": rec.get("age", ""),
                "gender": rec.get("gender", ""),
                "accents": rec.get("accent") or rec.get("accents") or "",
                "locale": rec.get("locale") or "sl",
                "segment": rec.get("segment", ""),
            }
            rows.append(row)
            count += 1
        _log(f"  split '{split}': {count} rows")
        if rows:
            break
    return rows


# ---------------------------------------------------------------------------
# Manifest + checksums
# ---------------------------------------------------------------------------

def _write_manifest(rows: Iterable[dict]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLS, delimiter="\t")
        w.writeheader()
        n = 0
        for row in rows:
            w.writerow({k: row.get(k, "") for k in MANIFEST_COLS})
            n += 1
    _log(f"wrote manifest {MANIFEST_PATH} ({n} rows)")


def _record_checksum(label: str, sha256_hex: str, origin: str) -> None:
    rel = Path(label)
    lines: list[str] = []
    if CHECKSUMS_PATH.exists():
        lines = [
            ln
            for ln in CHECKSUMS_PATH.read_text(encoding="utf-8").splitlines()
            if not ln.strip().endswith(label)
        ]
    lines.append(f"{sha256_hex}  {label}  {origin}  CC0-1.0")
    CHECKSUMS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"recorded checksum for {label}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _already_have_clips() -> bool:
    if not CLIPS_DIR.exists():
        return False
    have = any(CLIPS_DIR.glob("*.mp3")) or any(CLIPS_DIR.glob("*.wav"))
    return have and MANIFEST_PATH.exists()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="ignore existing clips")
    ap.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="cap HF streaming at N rows (0 = no cap)",
    )
    args = ap.parse_args()

    # Fresh log section
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"\n==== fetch_common_voice run ====\n")

    if _already_have_clips() and not args.force:
        _log("clips dir already populated -- skipping download (use --force to refresh)")
        return 0

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    origin_url = ""
    rows: list[dict] = []

    _log("probing direct S3 URLs for the Slovenian tarball ...")
    url = _probe_s3_url(session)
    if url:
        origin_url = url
        try:
            tar_path = _download_tarball(url, session)
            rows = _extract_tarball(tar_path)
            # Hash the tarball itself
            digest = _sha256_file(tar_path)
            _record_checksum(f"common_voice/{tar_path.name}", digest, url)
        except Exception as exc:
            _log(f"direct download failed: {exc}")
            rows = []

    if not rows:
        _log("falling back to Hugging Face datasets mirror ...")
        try:
            rows = _hf_fallback()
            origin_url = f"https://huggingface.co/datasets/{HF_DATASET}"
        except Exception as exc:
            _log(f"HF fallback failed: {exc}")
            return 2

    if args.max_rows and len(rows) > args.max_rows:
        rows = rows[: args.max_rows]

    _write_manifest(rows)
    digest = _sha256_file(MANIFEST_PATH)
    _record_checksum(
        "common_voice/manifest.tsv",
        digest,
        origin_url or "https://commonvoice.mozilla.org/en/datasets",
    )

    _log(f"DONE. clips={sum(1 for _ in CLIPS_DIR.glob('*.mp3'))} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
