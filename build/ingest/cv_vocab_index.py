"""Index the Common Voice manifest by MVP vocabulary tokens.

For each of the 181 MVP vocabulary tokens from ``build/_corpus_preview.json``,
find every Common Voice Slovenian clip whose sentence contains the token as a
standalone word (regex word boundary, case-insensitive).

Emits ``build/_cv_coverage.json`` mapping
    token -> [{"path": ..., "sentence": ..., "up_votes": int}, ...]
sorted descending by up_votes.

Prints a coverage summary: how many MVP tokens have >=1, >=3, >=5 clips.

Run:

    python -m build.ingest.cv_vocab_index
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "sources" / "common_voice" / "manifest.tsv"
CORPUS_PREVIEW = ROOT / "build" / "_corpus_preview.json"
OUT_PATH = ROOT / "build" / "_cv_coverage.json"
LOG_PATH = ROOT / "build" / "_cv.log"


def _log(msg: str) -> None:
    line = f"[cv_vocab_index] {msg}"
    print(line, flush=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _load_vocab() -> list[str]:
    data = json.loads(CORPUS_PREVIEW.read_text(encoding="utf-8"))
    vocab = data.get("vocab") or []
    if not vocab:
        raise RuntimeError(f"No 'vocab' in {CORPUS_PREVIEW}")
    return vocab


def _iter_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        raise RuntimeError(
            f"manifest not found: {MANIFEST_PATH} -- run fetch_common_voice first"
        )
    rows: list[dict] = []
    with MANIFEST_PATH.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            rows.append(row)
    return rows


def _as_int(val) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def main() -> int:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write("\n==== cv_vocab_index run ====\n")

    vocab = _load_vocab()
    _log(f"loaded {len(vocab)} MVP tokens from {CORPUS_PREVIEW.name}")

    rows = _iter_manifest()
    _log(f"loaded {len(rows)} manifest rows from {MANIFEST_PATH.name}")

    # Pre-compile a regex per token (word boundary, case-insensitive, unicode).
    # Using regex module for robust unicode word boundaries if available.
    try:
        import regex as _re

        compile_fn = lambda tok: _re.compile(
            r"(?<!\w)" + _re.escape(tok) + r"(?!\w)", flags=_re.IGNORECASE | _re.UNICODE
        )
    except ImportError:  # pragma: no cover
        compile_fn = lambda tok: re.compile(
            r"(?<!\w)" + re.escape(tok) + r"(?!\w)", flags=re.IGNORECASE | re.UNICODE
        )

    patterns = {tok: compile_fn(tok) for tok in vocab}
    index: dict[str, list[dict]] = defaultdict(list)

    for row in rows:
        sent = row.get("sentence") or ""
        if not sent:
            continue
        path = row.get("path") or ""
        up = _as_int(row.get("up_votes"))
        for tok, pat in patterns.items():
            if pat.search(sent):
                index[tok].append(
                    {"path": path, "sentence": sent, "up_votes": up}
                )

    # Sort each token's hits by up_votes desc
    out: dict[str, list[dict]] = {}
    for tok in vocab:
        hits = sorted(index.get(tok, []), key=lambda h: -h["up_votes"])
        out[tok] = hits

    OUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _log(f"wrote {OUT_PATH}")

    # Coverage summary
    counts = [len(out[t]) for t in vocab]
    ge1 = sum(1 for c in counts if c >= 1)
    ge3 = sum(1 for c in counts if c >= 3)
    ge5 = sum(1 for c in counts if c >= 5)
    total = len(vocab)
    summary = (
        f"coverage: {ge1}/{total} tokens >=1 clip | "
        f"{ge3}/{total} >=3 clips | {ge5}/{total} >=5 clips"
    )
    _log(summary)
    print(summary, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
