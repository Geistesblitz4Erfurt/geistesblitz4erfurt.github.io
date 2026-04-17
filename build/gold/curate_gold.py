"""Curate the deep-eval gold corpus.

Produces two artefacts consumed by ``build.validate.deep_validate``:

  build/_deep_eval_top500_words.json
    First 500 entries from build/_freq_vocab_top2000.json, enriched per word
    with {en_gloss, sloleks_ipa, stress_syl_idx, syllable_count, audio_path}.

  build/_deep_eval_50_sentences.json
    50 UD-SST sentences (from build/_udsst_gold_sentences.jsonl) filtered to:
      - sound_url present
      - 5 <= token count <= 12  (excluding punctuation)
      - pipeline coverage == 1.0
    Each record carries an EN gloss (via opus-mt-sla-en) and an expected
    contour_type derived from trailing punctuation.

Run::
    python -m build.gold.curate_gold
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "build" / "master.sqlite"
FREQ_VOCAB = ROOT / "build" / "_freq_vocab_top2000.json"
UDSST_JSONL = ROOT / "build" / "_udsst_gold_sentences.jsonl"
AUDIO_DIRS = [
    ROOT / "data" / "audio" / "words" / "lingualibre",
    ROOT / "data" / "audio" / "words",
]

OUT_WORDS = ROOT / "build" / "_deep_eval_top500_words.json"
OUT_SENTS = ROOT / "build" / "_deep_eval_50_sentences.json"

N_WORDS = 500
N_SENTS = 50
MIN_TOKS = 5
MAX_TOKS = 12


def _audio_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    for d in AUDIO_DIRS:
        if not d.exists():
            continue
        for p in d.iterdir():
            if p.suffix.lower() not in {".wav", ".ogg", ".oga", ".mp3"}:
                continue
            stem = p.stem
            if "_" in stem:
                word = stem.rsplit("_", 1)[0]
            else:
                word = stem
            idx.setdefault(word.lower(), str(p.relative_to(ROOT)).replace("\\", "/"))
    return idx


def _lookup_word(cur: sqlite3.Cursor, surface: str) -> dict[str, Any] | None:
    cur.execute(
        "SELECT ipa, syllables_json, stress_syllable_idx, accent_class "
        "FROM word_form WHERE LOWER(surface)=LOWER(?) AND ipa IS NOT NULL "
        "ORDER BY quality_score DESC, id ASC LIMIT 1",
        (surface,),
    )
    row = cur.fetchone()
    if not row:
        return None
    ipa, syll_json, stress_idx, accent = row
    try:
        syllables = json.loads(syll_json) if syll_json else []
    except Exception:
        syllables = []
    return {
        "sloleks_ipa": ipa,
        "syllables": syllables,
        "syllable_count": len(syllables),
        "stress_syl_idx": stress_idx,
        "accent_class": accent,
    }


def _glosser():
    from build.translate.bridge import bridge_sl_to_en

    cache: dict[str, str] = {}

    def g(sl: str) -> str:
        sl = sl.strip()
        if not sl:
            return ""
        if sl in cache:
            return cache[sl]
        try:
            out = bridge_sl_to_en(sl).strip()
        except Exception as exc:  # noqa: BLE001
            out = f"<err:{exc.__class__.__name__}>"
        cache[sl] = out
        return out

    return g


def _contour_from_text(text: str) -> str:
    s = text.strip()
    if s.endswith("?"):
        low = s.lower()
        wh = ("kdo", "kaj", "kdaj", "kje", "kam", "zakaj", "kako", "kateri", "katera", "katero", "koliko")
        if any(low.startswith(w + " ") or (" " + w + " ") in low for w in wh):
            return "q_wh"
        return "q_yn"
    if s.endswith("!"):
        return "excl"
    return "decl"


def curate_words() -> list[dict[str, Any]]:
    vocab = json.loads(FREQ_VOCAB.read_text(encoding="utf-8"))["vocab"]
    audio = _audio_index()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA query_only = 1;")
    cur = conn.cursor()
    gloss = _glosser()

    out: list[dict[str, Any]] = []
    for i, word in enumerate(vocab[:N_WORDS]):
        lk = _lookup_word(cur, word) or {
            "sloleks_ipa": None,
            "syllables": [],
            "syllable_count": 0,
            "stress_syl_idx": None,
            "accent_class": None,
        }
        rec: dict[str, Any] = {
            "rank": i + 1,
            "sl": word,
            "en_gloss": gloss(word),
            "audio_path": audio.get(word.lower()),
            **lk,
        }
        out.append(rec)
        if (i + 1) % 50 == 0:
            print(f"[gold/words] {i + 1}/{N_WORDS}", flush=True)
    conn.close()
    return out


def curate_sentences() -> list[dict[str, Any]]:
    from build.pipeline.synthesize import Synthesizer

    rows: list[dict[str, Any]] = []
    with UDSST_JSONL.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    candidates: list[dict[str, Any]] = []
    for r in rows:
        if not r.get("sound_url"):
            continue
        content_toks = [t for t in r.get("tokens", []) if t.get("upos") != "PUNCT"]
        if not (MIN_TOKS <= len(content_toks) <= MAX_TOKS):
            continue
        candidates.append(r)

    syn = Synthesizer()
    gloss = _glosser()
    out: list[dict[str, Any]] = []
    for r in candidates:
        if len(out) >= N_SENTS:
            break
        text = r["text"]
        try:
            res = syn.synthesize(text, lang="sl")
        except Exception as exc:  # noqa: BLE001
            print(f"[gold/sents] skip {r['sent_id']}: {exc}", flush=True)
            continue
        if res.get("coverage", 0.0) != 1.0:
            continue
        contour = _contour_from_text(text)
        rec = {
            "sent_id": r["sent_id"],
            "sl": text,
            "en_gloss": gloss(text),
            "sound_url": r["sound_url"],
            "speaker_id": r.get("speaker_id"),
            "expected_contour": contour,
            "pipeline_contour": res.get("contour_type"),
            "n_content_tokens": sum(1 for t in r.get("tokens", []) if t.get("upos") != "PUNCT"),
            "coverage": res.get("coverage"),
            "token_forms": [t.get("form") for t in r.get("tokens", [])],
            "upos_seq": [t.get("upos") for t in r.get("tokens", [])],
            "breaks": r.get("breaks"),
        }
        out.append(rec)
        if len(out) % 10 == 0:
            print(f"[gold/sents] {len(out)}/{N_SENTS}", flush=True)
    syn.close()
    return out


def main() -> int:
    print(f"[gold] curating top-{N_WORDS} words ...", flush=True)
    words = curate_words()
    OUT_WORDS.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[gold] wrote {OUT_WORDS} ({len(words)} records)", flush=True)

    print(f"[gold] curating {N_SENTS} sentences ...", flush=True)
    sents = curate_sentences()
    OUT_SENTS.write_text(json.dumps(sents, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[gold] wrote {OUT_SENTS} ({len(sents)} records)", flush=True)

    assert len(words) == N_WORDS, f"expected {N_WORDS} words, got {len(words)}"
    assert len(sents) == N_SENTS, f"expected {N_SENTS} sentences, got {len(sents)}"
    print("[gold] OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
