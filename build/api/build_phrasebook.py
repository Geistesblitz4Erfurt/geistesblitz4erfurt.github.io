"""Build the static EN→SL→SLPROS-1 phrasebook (the 'API' artefact).

Pipeline per seed prompt:
  1. Translate EN → SL via OPUS-MT (opus-mt-en-sla with >>slv<< prefix), GPU batched.
  2. Run the full build.pipeline.synthesize pipeline on the SL output:
     tokenise → Sloleks IPA (cascade → G2P) → sandhi → SLPROS-1.
  3. Derive a Web-Speech-API ``speech_directive`` (deterministic utterance spec).
  4. Filter to records with ``coverage == 1.0`` (zero missing IPA).

Output
------
  * ``data/api/phrasebook.json.gz`` — array of records (schema: docs/API_CONTRACT.md)
  * ``data/api/phrasebook_index.json`` — compact en-normalised → id index
    for O(1) client-side lookup
  * ``build/_phrasebook_build_stats.json`` — coverage, translation rate, failure log
  * updates ``data/manifest.json`` (sha1 + size of new artefacts)

Run::
    python -m build.api.build_phrasebook
    python -m build.api.build_phrasebook --batch-size 32 --num-beams 5
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from build.api.seed_en_prompts import generate as generate_seeds
from build.pipeline.synthesize import Synthesizer
from build.translate.bridge import translate_batch

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "api"
PHRASEBOOK_GZ = OUT_DIR / "phrasebook.json.gz"
PHRASEBOOK_INDEX = OUT_DIR / "phrasebook_index.json"
BUILD_STATS = ROOT / "build" / "_phrasebook_build_stats.json"
MANIFEST_PATH = ROOT / "data" / "manifest.json"

PIPELINE_VERSION = "1.0.0"

_NORMALIZE_RE = re.compile(r"[^\w\s]+", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")

# --- Linguistic-purity detectors (see docs/SPEECH_CONTRACT.md §2.2) -------
# Graphemes that MUST NOT appear in genuine Slovenian orthography.
# Hitting any one of these means the translator drifted into Croatian,
# Polish, Russian, etc. — drop the record.
_POISON_CHARS = frozenset(
    # Croatian / Bosnian / Serbian-Latin
    "ćĆđĐ"
    # Polish
    "łŁąĄęĘńŃóÓśŚźŹżŻ"
    # Digraphs that never occur in SL
    "ǉǈǊǋǌǍ"
)
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
# Slovenian-specific signal: words that reliably surface č/š/ž.
_SL_SIGNAL = frozenset("čČšŠžŽ")


def _purity_check(sl: str) -> tuple[bool, str | None, bool]:
    """Return (is_pure, reason_or_None, has_sl_signal).

    ``is_pure``: record can be shipped.
    ``reason``: diagnostic if rejected.
    ``has_sl_signal``: at least one č/š/ž present (for audit stats).
    """
    if not sl or not sl.strip():
        return False, "empty", False
    if _CYRILLIC_RE.search(sl):
        return False, "cyrillic", False
    for ch in sl:
        if ch in _POISON_CHARS:
            return False, f"poison:{ch}", False
    has_signal = any(ch in _SL_SIGNAL for ch in sl)
    return True, None, has_signal


def normalize_en(s: str) -> str:
    """Key for O(1) lookup: NFC-lower, strip punctuation, collapse whitespace."""
    import unicodedata
    s = unicodedata.normalize("NFC", s).lower()
    s = _NORMALIZE_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _derive_speech_directive(sl: str, slpros1: dict | None) -> dict:
    """Deterministic Web Speech API utterance spec.

    Rate is held at 1.0 (no speed hacks — the browser's SL voice, if present,
    produces natural-duration speech; shifting rate globally would damage
    naturalness and contradict the measured per-token SLPROS-1 timing).

    Pitch is held at 1.0 for the same reason: the browser voice has its own
    native baseline F0, and forcing a global pitch shift distorts without
    evidence. The per-syllable F0 contour in ``slpros1.tokens[*].syllables``
    is the true target — enforced by the word-concat fallback, not by
    Web Speech API (which does not expose per-syllable pitch control).
    """
    return {
        "text": sl,
        "lang": "sl-SI",
        "rate": 1.0,
        "pitch": 1.0,
        "volume": 1.0,
        "voice_preferences": [
            "Microsoft Lado",
            "Microsoft Lado - Slovenian (Slovenia)",
            "Google slovenščina",
            "Google Slovenian",
            "Lucia",
            "sl-SI",
            "sl_SI",
            "sl",
        ],
        "fallback": {
            "strategy": "concat_word_audio",
            "alt_strategy": "espeak_wasm_sl",
            "never_fall_back_to_other_language": True,
        },
        "max_chunk_ms": 12000,
        "spec_version": "W3C-WebSpeech",
        "spec_url": "https://webaudio.github.io/web-speech-api/",
        "events_consumed": ["start", "end", "error", "boundary", "pause", "resume"],
        "error_handling": {
            "retry_fallback_on": [
                "synthesis-failed",
                "synthesis-unavailable",
                "language-unavailable",
                "voice-unavailable",
                "audio-busy",
                "audio-hardware",
                "network",
            ],
            "surface_to_user": ["not-allowed", "text-too-long", "invalid-argument"],
            "silent_ignore": ["canceled", "interrupted"],
        },
        "boundary_hint": {
            "expected_name_values": ["word", "sentence"],
            "char_index_zero_if_unsupported": True,
        },
        "total_predicted_duration_ms": _estimate_duration_ms(slpros1) if slpros1 else None,
    }


def _estimate_duration_ms(slpros1: dict) -> int:
    """Sum of SLPROS-1 syllable durations + pauses (baseline 180 ms/syl)."""
    BASELINE_MS = 180
    total = 0
    for tok in slpros1.get("tokens", []):
        for sy in tok.get("syllables", []):
            total += int(round(sy["dur_rel"] * BASELINE_MS))
        total += int(tok.get("pause_after_ms", 0))
    total += int(slpros1.get("final_pause_ms", 500))
    return total


def _sha1(blob: bytes) -> str:
    return hashlib.sha1(blob).hexdigest()


def build(
    *,
    batch_size: int = 16,
    num_beams: int = 4,
    cpt_weight: float = 0.0,
) -> dict:
    seeds = generate_seeds()
    print(f"[phrasebook] {len(seeds)} seed prompts", flush=True)

    # --- Step 1: batched EN→SL translation (GPU if available) ---------
    t0 = time.time()
    en_texts = [s["en"] for s in seeds]
    sl_texts = translate_batch("en-sl", en_texts, batch_size=batch_size, num_beams=num_beams)
    dt_tr = time.time() - t0
    print(f"[phrasebook] translate done in {dt_tr:.1f}s ({len(sl_texts)/dt_tr:.1f}/s)", flush=True)
    assert len(sl_texts) == len(seeds), "translation count mismatch"

    # --- Step 2: run synthesis pipeline per record --------------------
    syn = Synthesizer(cpt_weight=cpt_weight)
    records: list[dict[str, Any]] = []
    dedup_keys: set[str] = set()
    dropped_no_coverage = 0
    dropped_empty = 0
    dropped_impure = 0
    purity_reasons: dict[str, int] = {}
    sl_signal_hits = 0

    gen_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        for i, (seed, sl) in enumerate(zip(seeds, sl_texts)):
            if not sl:
                dropped_empty += 1
                continue
            is_pure, why, has_signal = _purity_check(sl)
            if not is_pure:
                dropped_impure += 1
                purity_reasons[why or "unknown"] = purity_reasons.get(why or "unknown", 0) + 1
                continue
            if has_signal:
                sl_signal_hits += 1
            rec = syn.synthesize(sl, lang="sl", register=seed["register"])
            if rec.get("coverage", 0.0) < 0.999 or not rec.get("slpros1"):
                dropped_no_coverage += 1
                continue
            key = normalize_en(seed["en"])
            if key in dedup_keys:
                continue
            dedup_keys.add(key)

            records.append({
                "id": f"ph_{i:04d}",
                "en": seed["en"],
                "en_normalized": key,
                "category": seed["category"],
                "register": seed["register"],
                "sl": rec["sl"],
                "contour_type": rec["contour_type"],
                "coverage": rec["coverage"],
                "tokens": [
                    {
                        "surface": t["surface"],
                        "ipa": t.get("ipa_after_sandhi") or t.get("ipa"),
                        "ipa_pre_sandhi": t.get("ipa"),
                        "upos": t["upos"],
                        "role": t.get("role_after_sandhi") or t.get("role"),
                        "source": t["source"],
                        "sandhi_notes": t.get("sandhi_notes") or [],
                    }
                    for t in rec["tokens"]
                ],
                "slpros1": rec["slpros1"],
                "speech_directive": _derive_speech_directive(rec["sl"], rec["slpros1"]),
                "provenance": {
                    "translation_engine": "opus-mt-en-sla",
                    "translation_prefix": ">>slv<<",
                    "pipeline_version": PIPELINE_VERSION,
                    "generated_at": gen_at,
                },
            })
    finally:
        syn.close()

    print(
        f"[phrasebook] kept={len(records)} "
        f"dropped_empty={dropped_empty} "
        f"dropped_impure={dropped_impure} "
        f"dropped_no_coverage={dropped_no_coverage} "
        f"sl_signal_hits={sl_signal_hits}",
        flush=True,
    )
    if purity_reasons:
        print(f"[phrasebook] purity_reasons={purity_reasons}", flush=True)

    # --- Step 3: serialise --------------------------------------------
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(records, ensure_ascii=False).encode("utf-8")
    with gzip.open(PHRASEBOOK_GZ, "wb", compresslevel=9) as fh:
        fh.write(raw)
    gz_size = PHRASEBOOK_GZ.stat().st_size

    index = {r["en_normalized"]: r["id"] for r in records}
    PHRASEBOOK_INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- Step 4: stats + source breakdown -----------------------------
    from collections import Counter
    source_counter: Counter[str] = Counter()
    contour_counter: Counter[str] = Counter()
    sandhi_counter: Counter[str] = Counter()
    for r in records:
        contour_counter[r["contour_type"]] += 1
        for t in r["tokens"]:
            source_counter[t["source"]] += 1
            for n in t.get("sandhi_notes", []):
                sandhi_counter[n.split(":")[0]] += 1

    stats = {
        "n_seeds": len(seeds),
        "n_translated_non_empty": len(seeds) - dropped_empty,
        "n_records_shipped": len(records),
        "dropped_empty": dropped_empty,
        "dropped_impure": dropped_impure,
        "dropped_no_coverage": dropped_no_coverage,
        "purity": {
            "reasons": purity_reasons,
            "sl_signal_hits": sl_signal_hits,
            "sl_signal_rate": round(sl_signal_hits / max(1, len(records) + dropped_impure), 4),
        },
        "full_coverage_rate": (
            round(len(records) / max(1, len(seeds) - dropped_empty), 4)
        ),
        "phrasebook_gz_bytes": gz_size,
        "phrasebook_sha1": _sha1(raw),
        "source_distribution": dict(source_counter),
        "contour_distribution": dict(contour_counter),
        "sandhi_rule_triggers": dict(sandhi_counter),
        "translation_seconds": round(dt_tr, 2),
        "pipeline_version": PIPELINE_VERSION,
        "generated_at": gen_at,
    }
    BUILD_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- Step 5: update top-level manifest.json ----------------------
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    else:
        manifest = {}
    manifest.setdefault("counts", {})["phrasebook_records"] = len(records)
    manifest.setdefault("size_bytes", {})["phrasebook_gz"] = gz_size
    manifest.setdefault("sha1", {})["phrasebook"] = stats["phrasebook_sha1"]
    manifest["pipeline_version"] = PIPELINE_VERSION
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[phrasebook] wrote {PHRASEBOOK_GZ} ({gz_size/1024:.1f} kB gz)")
    print(f"[phrasebook] wrote {PHRASEBOOK_INDEX}")
    print(f"[phrasebook] wrote {BUILD_STATS}")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--num-beams", type=int, default=4)
    ap.add_argument("--cpt-weight", type=float, default=0.0)
    args = ap.parse_args()
    build(
        batch_size=args.batch_size,
        num_beams=args.num_beams,
        cpt_weight=args.cpt_weight,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
