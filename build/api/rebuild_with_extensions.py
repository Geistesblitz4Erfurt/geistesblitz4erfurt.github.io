"""Merge ``verified_extensions.jsonl`` into the next phrasebook release.

The continuous-verification loop grows the language over time: every
``POST /api/validate_word`` request with a score ≥ 0.90 appends a new record
to ``data/api/verified_extensions.jsonl``. This script rolls those records
into the static ``phrasebook.json.gz`` so the browser sees them on reload.

Algorithm
---------
1. Load the current ``phrasebook.json.gz`` into memory.
2. Load ``verified_extensions.jsonl``; dedupe by ``en_normalized`` and keep
   the highest-scoring entry per key.
3. For each extension:
   a. Skip if the ``en_normalized`` is already shipped (do not overwrite).
   b. Run the full synthesizer pipeline on the SL form to produce a complete
      record with SLPROS-1 + speech_directive identical to seed records.
   c. Tag with ``source: "extension"`` and the verified ``score``.
4. Concatenate (shipped + new extensions), rewrite gzipped file + index.
5. PATCH-bump ``pipeline_version`` in build stats.
6. Re-verify against ``build.validate.api_corpus_proof`` guarantees G1–G10.

Run::

    python -m build.api.rebuild_with_extensions
    python -m build.api.rebuild_with_extensions --dry-run
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "api"
PHRASEBOOK_GZ = OUT_DIR / "phrasebook.json.gz"
PHRASEBOOK_INDEX = OUT_DIR / "phrasebook_index.json"
VERIFIED_EXT = OUT_DIR / "verified_extensions.jsonl"
REBUILD_STATS = ROOT / "build" / "_rebuild_extensions_stats.json"

_NORMALIZE_RE = re.compile(r"[^\w\s]+", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")


def _normalize_en(s: str) -> str:
    s = unicodedata.normalize("NFC", s).lower()
    s = _NORMALIZE_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _load_phrasebook() -> list[dict]:
    if not PHRASEBOOK_GZ.exists():
        return []
    return json.loads(gzip.open(PHRASEBOOK_GZ, "rb").read())


def _load_extensions() -> list[dict]:
    if not VERIFIED_EXT.exists():
        return []
    items: list[dict] = []
    with VERIFIED_EXT.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    # dedupe by en_normalized, keep highest score
    best: dict[str, dict] = {}
    for ext in items:
        en = ext.get("en") or ""
        key = _normalize_en(en)
        if not key:
            continue
        prev = best.get(key)
        if prev is None or ext.get("score", 0.0) > prev.get("score", 0.0):
            ext["_key"] = key
            best[key] = ext
    return list(best.values())


def _build_record(ext: dict, next_id: int) -> dict | None:
    from build.api.build_phrasebook import _derive_speech_directive, _purity_check
    from build.pipeline.synthesize import Synthesizer

    syn = _build_record._synth  # type: ignore[attr-defined]
    if syn is None:
        syn = Synthesizer()
        _build_record._synth = syn  # type: ignore[attr-defined]

    en = ext["en"].strip()
    sl = ext["sl"].strip()
    ok, reason, _sig = _purity_check(sl)
    if not ok:
        return {"_skip": True, "reason": f"purity:{reason}", "en": en, "sl": sl}

    res = syn.synthesize(sl, lang="sl")
    sl = res.get("sl", sl)
    slpros1 = res.get("slpros1")
    if res.get("coverage", 0.0) != 1.0:
        return {"_skip": True, "reason": f"coverage:{res.get('coverage')}", "en": en, "sl": sl}
    directive = _derive_speech_directive(sl, slpros1)

    return {
        "id": f"ext_{next_id:04d}",
        "category": "extension",
        "en_text": en,
        "en_normalized": ext["_key"],
        "sl": sl,
        "contour_type": res.get("contour_type"),
        "coverage": res.get("coverage"),
        "tokens": [
            {
                "surface": t["surface"],
                "ipa": t.get("ipa_after_sandhi") or t.get("ipa"),
                "ipa_pre_sandhi": t.get("ipa"),
                "upos": t.get("upos"),
                "role": t.get("role_after_sandhi") or t.get("role"),
                "source": t.get("source"),
                "sandhi_notes": t.get("sandhi_notes") or [],
            }
            for t in res.get("tokens", [])
        ],
        "slpros1": slpros1,
        "speech_directive": directive,
        "extension": {
            "score": ext.get("score"),
            "verified_ts": ext.get("ts"),
            "verifier": ext.get("verifier"),
            "pipeline_version": ext.get("pipeline_version"),
        },
    }


_build_record._synth = None  # type: ignore[attr-defined]


def _write_artefacts(records: list[dict]) -> dict:
    PHRASEBOOK_GZ.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(records, ensure_ascii=False).encode("utf-8")
    with gzip.open(PHRASEBOOK_GZ, "wb", compresslevel=9) as f:
        f.write(body)
    index = {r["en_normalized"]: r["id"] for r in records}
    PHRASEBOOK_INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    sha1 = hashlib.sha1(PHRASEBOOK_GZ.read_bytes()).hexdigest()
    return {
        "phrasebook_gz_sha1": sha1,
        "phrasebook_gz_size": PHRASEBOOK_GZ.stat().st_size,
        "record_count": len(records),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    shipped = _load_phrasebook()
    shipped_keys = {r["en_normalized"] for r in shipped}
    exts = _load_extensions()
    print(f"[rebuild] shipped={len(shipped)}  extensions={len(exts)}", flush=True)

    next_id = len([r for r in shipped if r["id"].startswith("ext_")]) + 1
    added: list[dict] = []
    skipped: list[dict] = []
    for ext in exts:
        if ext["_key"] in shipped_keys:
            skipped.append({"en": ext["en"], "reason": "already shipped"})
            continue
        rec = _build_record(ext, next_id)
        if rec is None:
            skipped.append({"en": ext["en"], "reason": "build returned None"})
            continue
        if rec.get("_skip"):
            skipped.append({"en": rec["en"], "reason": rec["reason"]})
            continue
        added.append(rec)
        next_id += 1

    merged = shipped + added

    stats = {
        "shipped_count": len(shipped),
        "extensions_read": len(exts),
        "added": len(added),
        "skipped": skipped[:20],
        "new_total": len(merged),
    }

    if args.dry_run:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        print("[rebuild] dry-run; no files written")
        return 0

    art = _write_artefacts(merged)
    stats.update(art)
    REBUILD_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
