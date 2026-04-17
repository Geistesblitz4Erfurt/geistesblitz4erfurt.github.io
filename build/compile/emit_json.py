"""Compile master DB + MVP-SLPROS-1 artefact into browser-ready ``data/*.json.gz``.

Emits:
  data/words.json.gz         { surface: {ipa, accent_class, syllables, stress_idx, quality,
                                        audio: [...], pos: [msd-first-letter list] } }
  data/sentences.json.gz     { id: {sl, en, category, register, contour_type, tokens, slpros1} }
  data/audio_manifest.json   list of audio files with license + format + speaker meta
  data/validation_report.json  copied forward (rich report pre-built by build.validate.*)
  data/manifest.json         { build_time, counts, size_bytes, contents-hash }

Vocabulary policy:
  * emit every word_form that appears (case-insensitively) in the 151 MVP sentences
  * plus the intersection of the top-2000 frequency list × Sloleks (for future-growth)
  * all emitted forms must have IPA; rows without IPA are deferred
Audio policy:
  * only rows whose ``local_path`` exists on disk go into the manifest; the DB may
    reference files we chose not to redistribute (validation-only)
  * the emitted ``path`` is web-relative (forward slashes, relative to /data)
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "build" / "master.sqlite"
MVP_PATH = ROOT / "build" / "_mvp_slpros1.json"
FREQ_PATH = ROOT / "build" / "_freq_vocab_top2000.json"
VALIDATION_REPORT_IN = ROOT / "data" / "validation_report.json"
OUT_DIR = ROOT / "data"

QUALITY_THRESHOLD = 0.6
DEFAULT_EXTRA_FREQ = 2000


def _sha1(blob: bytes) -> str:
    return hashlib.sha1(blob).hexdigest()


def _gz_write(path: Path, payload) -> tuple[int, int, str]:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb", compresslevel=9) as fh:
        fh.write(raw)
    gz_bytes = path.stat().st_size
    return len(raw), gz_bytes, _sha1(raw)


def _collect_surfaces(mvp_sentences: list[dict], freq_list: list[str]) -> set[str]:
    surfaces: set[str] = set()
    for s in mvp_sentences:
        for t in s["tokens"]:
            surfaces.add(t["surface"])
    for f in freq_list:
        if f:
            surfaces.add(f)
    return surfaces


def _webpath(p: str) -> str:
    """Convert a DB-stored path (e.g. ``data\\audio\\...``) to a web-relative one."""
    rel = p.replace("\\", "/")
    if rel.startswith("data/"):
        rel = rel[5:]
    return rel


def _compile_words(
    conn: sqlite3.Connection,
    surfaces: set[str],
) -> tuple[dict, list, dict]:
    """Return (words, deferred, audio_manifest).

    Only surfaces from ``surfaces`` are considered. Audio is attached whenever a
    word_form row has a matching ``audio_asset`` AND the file exists on disk.
    """
    cur = conn.cursor()
    audio_used: dict[str, dict] = {}

    # Build case-insensitive surface filter
    wanted = {s.lower() for s in surfaces}
    # fetch all word_form rows in one pass (cheaper than a case-insensitive IN clause of 2k+ items)
    cur.execute(
        "SELECT id, surface, msd, ipa, accent_class, syllables_json, stress_syllable_idx, "
        "quality_score, source_mask FROM word_form WHERE ipa IS NOT NULL AND ipa != ''"
    )
    # group by surface (case-insensitive): pick the highest quality per (surface_ci)
    best: dict[str, dict] = {}
    alt_msds: dict[str, list[str]] = defaultdict(list)
    for wfid, surface, msd, ipa, ac, sj, idx, q, mask in cur.fetchall():
        key = surface.lower()
        if key not in wanted:
            continue
        entry = {
            "_wfid": wfid,
            "surface": surface,
            "ipa": ipa,
            "accent_class": ac or "-",
            "syllables": json.loads(sj) if sj else [],
            "stress_syllable_idx": idx if idx is not None else -1,
            "quality": round(q or 0.0, 3),
            "sources": mask or 0,
            "msd": msd or "",
        }
        prev = best.get(key)
        if (prev is None) or (entry["quality"] > prev["quality"]):
            best[key] = entry
        if msd:
            alt_msds[key].append(msd)

    # Attach audio from audio_asset rows whose file exists on disk
    audio_rows = cur.execute(
        "SELECT word_form_id, local_path, format, source, license, duration_ms, "
        "speaker_meta, f0_baseline_hz FROM audio_asset"
    ).fetchall()
    by_wfid: dict[int, list[dict]] = defaultdict(list)
    for wfid, path, fmt, source, lic, dur, speaker, f0 in audio_rows:
        if not path:
            continue
        abs_path = ROOT / path
        if not abs_path.exists():
            continue
        web = _webpath(path)
        rec = {
            "path": web,
            "format": fmt,
            "source": source,
            "license": lic,
            "duration_ms": dur,
            "speaker_meta": json.loads(speaker) if speaker else None,
        }
        by_wfid[wfid].append(rec)
        audio_used[web] = rec

    words: dict[str, dict] = {}
    deferred: list[dict] = []
    for key, e in best.items():
        audio = by_wfid.get(e["_wfid"], [])
        payload = {
            "surface": e["surface"],
            "ipa": e["ipa"],
            "accent_class": e["accent_class"],
            "syllables": e["syllables"],
            "stress_syllable_idx": e["stress_syllable_idx"],
            "quality": e["quality"],
            "sources": e["sources"],
            "msd": e["msd"],
            "msd_variants": sorted(set(alt_msds.get(key, []))),
            "audio": audio,
        }
        if e["quality"] < QUALITY_THRESHOLD:
            deferred.append(payload)
            continue
        words[key] = payload
    return words, deferred, audio_used


def _compile_sentences(mvp: dict) -> dict:
    out: dict[str, dict] = {}
    for s in mvp["sentences"]:
        tokens = []
        for t in s["tokens"]:
            tokens.append({
                "surface": t["surface"],
                "ipa": t["ipa"],
                "upos": t["upos"],
                "role": t["role"],
            })
        slpros = s.get("slpros1")
        trimmed = None
        if slpros:
            trimmed = {
                "contour_type": slpros["contour_type"],
                "register": slpros["register"],
                "baseline_f0_hz": slpros["baseline_f0_hz"],
                "final_pause_ms": slpros["final_pause_ms"],
                "tokens": [
                    {
                        "surface": t["surface"],
                        "ipa": t["ipa"],
                        "role": t["role"],
                        "accent_class": t["accent_class"],
                        "stress_syllable_idx": t["stress_syllable_idx"],
                        "syllables": t["syllables"],
                        "pause_after_ms": t["pause_after_ms"],
                        "f0_contour_tag": t["f0_contour_tag"],
                    }
                    for t in slpros["tokens"]
                ],
            }
        out[s["id"]] = {
            "sl": s["sl"],
            "en": s["en"],
            "category": s.get("category"),
            "register": s.get("register", "formal"),
            "contour_type": s["contour_type"],
            "coverage": s["coverage"],
            "tokens": tokens,
            "slpros1": trimmed,
        }
    return out


def run(db_path: Path, mvp_path: Path, freq_path: Path, out_dir: Path) -> dict:
    mvp = json.loads(mvp_path.read_text(encoding="utf-8"))
    freq = json.loads(freq_path.read_text(encoding="utf-8"))["vocab"] if freq_path.exists() else []

    surfaces = _collect_surfaces(mvp["sentences"], freq[:DEFAULT_EXTRA_FREQ])
    conn = sqlite3.connect(db_path)
    try:
        words, deferred, audio_used = _compile_words(conn, surfaces)
    finally:
        conn.close()
    sentences = _compile_sentences(mvp)

    # Fill in any MVP token surface that the DB-based pass missed
    # (e.g. the preposition ``z``, which has NULL ipa in Sloleks).
    # We trust the MVP resolver's IPA because coverage was already validated.
    for s in mvp["sentences"]:
        for t in s["tokens"]:
            if not t["ipa"]:
                continue
            key = t["surface"].lower()
            if key in words:
                continue
            words[key] = {
                "surface": t["surface"],
                "ipa": t["ipa"],
                "accent_class": "-",
                "syllables": [],
                "stress_syllable_idx": -1,
                "quality": 0.75,
                "sources": 0,
                "msd": "",
                "msd_variants": [],
                "audio": [],
                "fallback_source": t["source"],
            }

    out_dir.mkdir(parents=True, exist_ok=True)
    words_raw, words_gz, words_sha = _gz_write(out_dir / "words.json.gz", words)
    sents_raw, sents_gz, sents_sha = _gz_write(out_dir / "sentences.json.gz", sentences)

    # deferred: tiny, plain JSON
    (out_dir / "deferred.json").write_text(
        json.dumps(deferred, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # audio manifest
    manifest_audio = sorted(audio_used.values(), key=lambda r: r["path"])
    (out_dir / "audio_manifest.json").write_text(
        json.dumps(manifest_audio, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # top-level manifest
    manifest = {
        "build_time": int(time.time()),
        "counts": {
            "words": len(words),
            "sentences": len(sentences),
            "deferred_words": len(deferred),
            "audio_files": len(manifest_audio),
            "mvp_token_coverage": mvp.get("n_tokens"),
        },
        "size_bytes": {
            "words_gz": words_gz,
            "words_raw": words_raw,
            "sentences_gz": sents_gz,
            "sentences_raw": sents_raw,
        },
        "sha1": {
            "words": words_sha,
            "sentences": sents_sha,
        },
        "mvp_source_breakdown": mvp.get("token_source_breakdown"),
        "license": "CC-BY-SA 4.0 (inherits from Sloleks 3.1)",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[compile] words={len(words)} ({words_gz/1024:.1f} kB gz) | "
        f"sentences={len(sentences)} ({sents_gz/1024:.1f} kB gz) | "
        f"deferred={len(deferred)} | audio={len(manifest_audio)}"
    )
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--mvp", type=Path, default=MVP_PATH)
    ap.add_argument("--freq", type=Path, default=FREQ_PATH)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    run(args.db, args.mvp, args.freq, args.out)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
