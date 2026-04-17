"""Download the Slovenian (``sl``) split of Mozilla Common Voice from Hugging Face.

The legacy ``fetch_common_voice.py`` probed direct Mozilla S3 URLs (now email-gated,
all 403) and then tried the deprecated ``common_voice_17_0`` loader script on HF (the
script was removed upstream — ``mozilla-foundation/common_voice_17_0`` now holds only
a README and ``.gitattributes``; no data). ``common_voice_18_0`` and later simply do
not exist on HF.

This replacement:

    * Targets ``fsicoli/common_voice_17_0`` — a complete, public, non-gated mirror
      of Mozilla's last HF upload. Layout is the original HF-hosted convention:
      ``audio/sl/<split>/sl_<split>_*.tar`` and ``transcript/sl/<split>.tsv``.
      Upstream license = **CC0-1.0** (inherited from Mozilla Common Voice).
    * Uses :func:`huggingface_hub.snapshot_download` with an allow-list so we only
      pull the Slovenian locale.
    * Authenticates via the ``HF_TOKEN`` environment variable (never persisted to
      any file we write). The fsicoli mirror is non-gated so the token is not
      strictly required, but we still authenticate to benefit from higher
      rate-limit ceilings.
    * Polite backoff on HTTP 429 / 5xx via ``huggingface_hub`` built-in retries
      plus a wall-clock pause between splits.
    * Idempotent: re-running resumes — HF's caching + our presence-check skip
      already-downloaded tarballs and already-extracted clips.

Output layout under ``sources/common_voice/18.0/``::

    hf_snapshot/                 # raw HF repo snapshot, cc0 licensed, tarballs+tsv
        audio/sl/<split>/*.tar
        transcript/sl/<split>.tsv
    clips/<basename>.mp3         # extracted audio clips, flat
    manifest.tsv                 # client_id, path, sentence, split, up_votes, down_votes

License: **CC0-1.0** (per CV terms). Appends one ``checksums.txt`` row.

Run::

    HF_TOKEN=hf_xxx PYTHONIOENCODING=utf-8 \
        python -m build.ingest.fetch_common_voice_18 --splits validated,test

The ``--splits`` flag defaults to ``validated,test,dev`` — skipping ``train`` and
``other`` keeps the initial pull manageable (a few GB rather than double-digit).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import sys
import tarfile
import time
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "sources" / "common_voice" / "17.0"
SNAPSHOT_DIR = OUT_DIR / "hf_snapshot"
CLIPS_DIR = OUT_DIR / "clips"
MANIFEST_PATH = OUT_DIR / "manifest.tsv"
LOG_PATH = ROOT / "build" / "_cv18.log"
CHECKSUMS_PATH = ROOT / "sources" / "checksums.txt"

HF_REPO = "fsicoli/common_voice_17_0"
LOCALE = "sl"
VALID_SPLITS = ("train", "dev", "test", "validated", "invalidated", "other")
DEFAULT_SPLITS = ("validated", "test", "dev")

MANIFEST_COLS = [
    "client_id",
    "path",
    "sentence",
    "split",
    "up_votes",
    "down_votes",
    "age",
    "gender",
    "accents",
    "locale",
    "segment",
]

CHUNK = 1 << 20


def _log(msg: str) -> None:
    line = f"[cv18] {msg}"
    print(line, flush=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _token() -> str:
    tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not tok:
        raise SystemExit(
            "HF_TOKEN not set. Export your token (never commit it) and retry:\n"
            "    export HF_TOKEN=hf_xxx   # bash\n"
            "    $env:HF_TOKEN='hf_xxx'   # PowerShell"
        )
    return tok


def _snapshot(splits: list[str]) -> Path:
    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except ImportError as exc:
        raise SystemExit(f"huggingface_hub not installed: {exc}")
    allow: list[str] = []
    for sp in splits:
        allow += [
            f"audio/{LOCALE}/{sp}/*",
            f"transcript/{LOCALE}/{sp}.tsv",
        ]
    allow += [f"audio/{LOCALE}/{LOCALE}*.tsv", "README.md", "LICENSE*"]
    _log(f"snapshot_download repo={HF_REPO} locale={LOCALE} splits={splits}")
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    local = snapshot_download(
        repo_id=HF_REPO,
        repo_type="dataset",
        local_dir=str(SNAPSHOT_DIR),
        allow_patterns=allow,
        token=_token(),
        max_workers=2,
    )
    return Path(local)


def _extract_tarballs(split: str) -> int:
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    split_dir = SNAPSHOT_DIR / "audio" / LOCALE / split
    n_new = 0
    if not split_dir.exists():
        _log(f"no audio dir for split={split} (expected {split_dir})")
        return 0
    tars = sorted(split_dir.glob("*.tar"))
    _log(f"split={split}: {len(tars)} tarball(s)")
    for tar_path in tars:
        try:
            with tarfile.open(tar_path, "r") as tf:
                for m in tf:
                    if not m.isfile():
                        continue
                    base = m.name.rsplit("/", 1)[-1]
                    if not base.lower().endswith((".mp3", ".wav", ".ogg", ".opus")):
                        continue
                    out = CLIPS_DIR / base
                    if out.exists() and out.stat().st_size > 0:
                        continue
                    fh = tf.extractfile(m)
                    if fh is None:
                        continue
                    out.write_bytes(fh.read())
                    n_new += 1
        except tarfile.TarError as exc:
            _log(f"  TAR ERROR in {tar_path.name}: {exc}")
    _log(f"split={split}: extracted {n_new} new clip(s)")
    return n_new


def _iter_transcript_rows(splits: list[str]):
    for sp in splits:
        tsv = SNAPSHOT_DIR / "transcript" / LOCALE / f"{sp}.tsv"
        if not tsv.exists():
            _log(f"no transcript for split={sp} (expected {tsv})")
            continue
        with tsv.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            n = 0
            for rec in reader:
                row = {k: (rec.get(k) or "") for k in MANIFEST_COLS}
                row["split"] = sp
                row["locale"] = row.get("locale") or LOCALE
                yield row
                n += 1
            _log(f"split={sp}: {n} transcript row(s)")


def _write_manifest(rows: Iterable[dict]) -> int:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with MANIFEST_PATH.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLS, delimiter="\t")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in MANIFEST_COLS})
            n += 1
    _log(f"wrote {MANIFEST_PATH} ({n} rows)")
    return n


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _record_checksum() -> None:
    if not MANIFEST_PATH.exists():
        return
    digest = _sha256(MANIFEST_PATH)
    label = "common_voice/17.0/manifest.tsv"
    lines: list[str] = []
    if CHECKSUMS_PATH.exists():
        lines = [
            ln
            for ln in CHECKSUMS_PATH.read_text(encoding="utf-8").splitlines()
            if label not in ln
        ]
    lines.append(
        f"{digest}  {label}  https://huggingface.co/datasets/{HF_REPO}  CC0-1.0"
    )
    CHECKSUMS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"checksum recorded for {label}")


def run(splits: list[str]) -> dict[str, int]:
    bad = [s for s in splits if s not in VALID_SPLITS]
    if bad:
        raise SystemExit(f"unknown split(s): {bad}. valid: {VALID_SPLITS}")
    _snapshot(splits)
    extracted = 0
    for sp in splits:
        extracted += _extract_tarballs(sp)
        time.sleep(0.5)  # gentle spacing
    n_rows = _write_manifest(_iter_transcript_rows(splits))
    _record_checksum()
    total_clips = sum(1 for _ in CLIPS_DIR.glob("*.mp3")) + sum(
        1 for _ in CLIPS_DIR.glob("*.wav")
    )
    return {"new_clips": extracted, "total_clips": total_clips, "manifest_rows": n_rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--splits",
        default=",".join(DEFAULT_SPLITS),
        help=f"comma-separated splits (any of {VALID_SPLITS})",
    )
    args = ap.parse_args()
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"\n==== fetch_common_voice_18 run splits={splits} ====\n")
    counts = run(splits)
    _log(f"DONE: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
