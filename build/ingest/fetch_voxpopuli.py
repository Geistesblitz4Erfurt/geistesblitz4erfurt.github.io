"""Fetch the Slovenian subset of facebook/voxpopuli (CC0, European Parliament recordings).

Three Parquet files (train/validation/test) contain audio bytes + transcripts. CC0 license
allows full redistribution. Slovene MEPs → formal register, useful for acoustic modelling and
as a validation corpus for our ljubljana-standard pronunciation.

Run::

    python -m build.ingest.fetch_voxpopuli
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "sources" / "voxpopuli_sl"
CHECKSUMS = REPO_ROOT / "sources" / "checksums.txt"


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[voxpopuli] downloading sl/ parquets to {OUT_DIR}")
    snapshot_download(
        repo_id="facebook/voxpopuli",
        repo_type="dataset",
        local_dir=str(OUT_DIR),
        allow_patterns=["sl/*.parquet", "README.md", "LICENSE*"],
    )
    files = sorted(OUT_DIR.rglob("*.parquet"))
    print(f"[voxpopuli] {len(files)} parquet file(s):")
    total = 0
    for f in files:
        sz = f.stat().st_size
        total += sz
        print(f"  {sz/1e6:8.2f} MB  {f.relative_to(OUT_DIR)}")
    print(f"[voxpopuli] total {total/1e6:.1f} MB")

    # checksums
    line = (
        f"SNAPSHOT  sources/voxpopuli_sl  "
        f"https://huggingface.co/datasets/facebook/voxpopuli  CC0-1.0"
    )
    CHECKSUMS.parent.mkdir(parents=True, exist_ok=True)
    existing = CHECKSUMS.read_text(encoding="utf-8") if CHECKSUMS.exists() else ""
    kept = [ln for ln in existing.splitlines() if "voxpopuli_sl" not in ln]
    kept.append(line)
    CHECKSUMS.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.parse_args()
    return run()


if __name__ == "__main__":
    sys.exit(main())
