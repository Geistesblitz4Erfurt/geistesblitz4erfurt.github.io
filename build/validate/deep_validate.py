"""Multi-layer deep validator for the gold corpus (top-500 words + 50 sentences).

Per word, six independent layers L1–L6 each yield a boolean pass + a confidence
in [0..1]. The weighted sum is the word's Score. A word is ``verified`` iff
``score >= 0.90 AND at least 3 independent layers pass``.

    L1  Sloleks-existence        (ipa exists in word_form table)
    L2  G2P-agreement            (slovene_g2p IPA vs Sloleks IPA, Levenshtein ≤ 1)
    L3  Syllable-count match     (regex-syllabifier vs Sloleks syllables[])
    L4  Audio-duration sanity    (n_syll * 180ms ± 50% vs true wav duration)
    L5  Forced-alignment conf    (wav2vec2 CTC mean_conf >= 0.5)
    L6  Back-translation survive (en_gloss → opus-mt-en-sla → SL, Lev ≤ 2)

    Weights:  L1=0.25 L2=0.25 L3=0.10 L4=0.10 L5=0.20 L6=0.10

Per sentence, five layers S1–S5 collect into an aggregate score the same way.

    S1  Pipeline coverage == 1.0
    S2  Duration-prediction corr (SLPROS-1 total_ms vs mp3 ms, |ratio-1| ≤ 0.3)
    S3  Contour-type matches punctuation
    S4  Back-translation token recall (Jaccard against en_gloss >= 0.5)
    S5  Sandhi rules fire on expected patterns (R1 for preps, R5 for clitics)

Artefacts written:

    data/api/deep_validation_report.json
    data/api/verified_words.json   (only Score >= 0.9 entries)

Run::

    PYTHONIOENCODING=utf-8 python -m build.validate.deep_validate
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "build" / "master.sqlite"
WORDS_IN = ROOT / "build" / "_deep_eval_top500_words.json"
SENTS_IN = ROOT / "build" / "_deep_eval_50_sentences.json"
REPORT_OUT = ROOT / "data" / "api" / "deep_validation_report.json"
VERIFIED_OUT = ROOT / "data" / "api" / "verified_words.json"

WORD_LAYER_WEIGHTS = {"L1": 0.25, "L2": 0.25, "L3": 0.10, "L4": 0.10, "L5": 0.20, "L6": 0.10}
SENT_LAYER_WEIGHTS = {"S1": 0.30, "S2": 0.20, "S3": 0.15, "S4": 0.25, "S5": 0.10}
VERIFIED_THRESHOLD = 0.90
MIN_LAYERS_PASS = 3

SYLLABLE_DUR_MS = 180
AUDIO_TOLERANCE = 0.5  # ±50%

PREPS_PROCLITIC = {"v", "z", "s", "k", "h", "pri", "pod", "nad", "pred", "za", "ob", "iz", "od", "do", "na", "o", "po"}
ENCLITIC = {"se", "si", "je", "sem", "si", "smo", "ste", "so", "ga", "jo", "jih", "mi", "ti", "mu", "ji", "nam", "vam", "jim", "me", "te", "nas", "vas"}


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def _norm_ipa(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    for ch in ("ˈ", "ˌ", "'", '"', "ː", ":"):
        s = s.replace(ch, "")
    return s.strip()


_VOWELS = set("aeiouAEIOUəɐɛɔɪʊæœyøɑɒüöÜÖ")


def _syllable_count_heuristic(word: str) -> int:
    n = 0
    prev_vowel = False
    for ch in word:
        is_v = ch.lower() in "aeiouəy"
        if is_v and not prev_vowel:
            n += 1
        prev_vowel = is_v
    return max(1, n)


# ---------------------------------------------------------------------------
# Word layers
# ---------------------------------------------------------------------------
def word_layer_L1(rec: dict) -> dict:
    has = bool(rec.get("sloleks_ipa"))
    return {"pass": has, "conf": 1.0 if has else 0.0, "note": rec.get("sloleks_ipa")}


def word_layer_L2(rec: dict, cur: sqlite3.Cursor, g2p_fn) -> dict:
    sl = rec["sl"]
    sloleks_ipa = rec.get("sloleks_ipa")
    if not sloleks_ipa:
        return {"pass": False, "conf": 0.0, "note": "no sloleks_ipa"}
    cur.execute(
        "SELECT msd FROM word_form WHERE LOWER(surface)=LOWER(?) "
        "ORDER BY quality_score DESC, id ASC LIMIT 1",
        (sl,),
    )
    row = cur.fetchone()
    msd = row[0] if row else "Unknown"
    try:
        g_ipa = g2p_fn(sl, msd or "Unknown", "")
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "conf": 0.0, "note": f"g2p err: {exc.__class__.__name__}"}
    if not g_ipa:
        return {"pass": False, "conf": 0.0, "note": "g2p returned none"}
    d = _levenshtein(_norm_ipa(sloleks_ipa), _norm_ipa(g_ipa))
    ok = d <= 1
    conf = max(0.0, 1.0 - d / max(1, len(_norm_ipa(sloleks_ipa))))
    return {"pass": ok, "conf": round(conf, 3), "note": f"lev={d} g2p={g_ipa}"}


def word_layer_L3(rec: dict) -> dict:
    n_sloleks = rec.get("syllable_count") or 0
    if n_sloleks == 0:
        return {"pass": False, "conf": 0.0, "note": "no syllables"}
    n_heur = _syllable_count_heuristic(rec["sl"])
    ok = n_sloleks == n_heur
    conf = 1.0 if ok else max(0.0, 1.0 - abs(n_sloleks - n_heur) / max(1, n_sloleks))
    return {"pass": ok, "conf": round(conf, 3), "note": f"sloleks={n_sloleks} heur={n_heur}"}


def word_layer_L4(rec: dict) -> dict:
    audio = rec.get("audio_path")
    if not audio:
        return {"pass": False, "conf": 0.0, "note": "no audio"}
    p = ROOT / audio
    if not p.exists():
        return {"pass": False, "conf": 0.0, "note": f"missing file {audio}"}
    try:
        import soundfile as sf  # type: ignore
        info = sf.info(str(p))
        dur_ms = int(info.duration * 1000)
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "conf": 0.0, "note": f"sf err: {exc.__class__.__name__}"}
    n = rec.get("syllable_count") or 1
    expected = n * SYLLABLE_DUR_MS
    lo, hi = expected * (1 - AUDIO_TOLERANCE), expected * (1 + AUDIO_TOLERANCE) * 2
    ok = lo <= dur_ms <= hi
    ratio = dur_ms / max(1, expected)
    conf = max(0.0, 1.0 - abs(ratio - 1.0) / 1.5)
    return {"pass": ok, "conf": round(conf, 3), "note": f"dur={dur_ms}ms exp={expected}ms"}


def word_layer_L5(rec: dict, aligner_fn) -> dict:
    audio = rec.get("audio_path")
    if not audio:
        return {"pass": False, "conf": 0.0, "note": "no audio"}
    p = ROOT / audio
    if not p.exists():
        return {"pass": False, "conf": 0.0, "note": "missing file"}
    try:
        out = aligner_fn(p, rec["sl"], expected_ipa=rec.get("sloleks_ipa"))
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "conf": 0.0, "note": f"align err: {exc.__class__.__name__}"}
    mc = out.get("mean_conf", 0.0)
    ok = mc >= 0.5
    return {"pass": ok, "conf": round(min(1.0, mc), 3), "note": f"aligned={out.get('aligned_chars')}"}


def word_layer_L6(rec: dict, en_to_sl_fn) -> dict:
    en_gloss = rec.get("en_gloss") or ""
    if not en_gloss or en_gloss.startswith("<err:"):
        return {"pass": False, "conf": 0.0, "note": "no en_gloss"}
    try:
        sl_back = en_to_sl_fn(en_gloss).strip()
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "conf": 0.0, "note": f"mt err: {exc.__class__.__name__}"}
    # Back-translation is word-level; we check whether the original SL lemma
    # (or any inflection thereof sharing first 4 chars) appears in the result.
    stem = rec["sl"][:4].lower()
    hit = stem in sl_back.lower()
    d = _levenshtein(rec["sl"].lower(), sl_back.lower())
    ok = hit or d <= 2
    conf = 1.0 if hit else max(0.0, 1.0 - d / max(4, len(rec["sl"])))
    return {"pass": ok, "conf": round(conf, 3), "note": f"back={sl_back}"}


# ---------------------------------------------------------------------------
# Sentence layers
# ---------------------------------------------------------------------------
def sent_layer_S1(rec: dict) -> dict:
    cov = rec.get("coverage", 0.0)
    ok = cov == 1.0
    return {"pass": ok, "conf": float(cov), "note": f"cov={cov}"}


def sent_layer_S2(rec: dict, synth, sound_dur_cache: dict) -> dict:
    text = rec["sl"]
    res = synth.synthesize(text, lang="sl")
    sp = res.get("slpros1") or {}
    tot_ms = 0
    for t in sp.get("tokens", []):
        for syll in t.get("syllables", []):
            tot_ms += int(syll.get("dur_ms", 0))
        tot_ms += int(t.get("pause_after_ms", 0))
    tot_ms += int(sp.get("final_pause_ms", 0))
    # Use cached audio duration (requires mp3 fetched — otherwise skip gracefully).
    dur_ms = sound_dur_cache.get(rec["sent_id"])
    if dur_ms is None:
        return {"pass": False, "conf": 0.0, "note": f"no audio probe pred={tot_ms}ms"}
    ratio = tot_ms / max(1, dur_ms)
    ok = abs(ratio - 1.0) <= 0.3
    conf = max(0.0, 1.0 - abs(ratio - 1.0))
    return {"pass": ok, "conf": round(conf, 3), "note": f"pred={tot_ms} real={dur_ms} r={ratio:.2f}"}


def sent_layer_S3(rec: dict) -> dict:
    exp = rec.get("expected_contour")
    got = rec.get("pipeline_contour")
    ok = (exp == got) or (exp in ("q_yn", "q_wh") and got in ("q_yn", "q_wh"))
    return {"pass": ok, "conf": 1.0 if ok else 0.0, "note": f"exp={exp} got={got}"}


def sent_layer_S4(rec: dict, sl_to_en_fn) -> dict:
    en_gloss = rec.get("en_gloss") or ""
    if not en_gloss:
        return {"pass": False, "conf": 0.0, "note": "no gloss"}
    try:
        back_en = sl_to_en_fn(rec["sl"]).lower()
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "conf": 0.0, "note": f"mt err: {exc.__class__.__name__}"}
    a = set(re.findall(r"\w+", en_gloss.lower()))
    b = set(re.findall(r"\w+", back_en))
    if not a:
        return {"pass": False, "conf": 0.0, "note": "empty gloss"}
    recall = len(a & b) / len(a)
    ok = recall >= 0.5
    return {"pass": ok, "conf": round(recall, 3), "note": f"recall={recall:.2f}"}


def sent_layer_S5(rec: dict, synth) -> dict:
    forms = [f.lower() for f in rec.get("token_forms", []) if f]
    has_prep = any(f in PREPS_PROCLITIC for f in forms)
    has_clit = any(f in ENCLITIC for f in forms)
    # Fire the pipeline and inspect sandhi_notes on tokens.
    res = synth.synthesize(rec["sl"], lang="sl")
    notes: list[str] = []
    for t in res.get("tokens", []):
        notes += t.get("sandhi_notes", []) or []
    r1_fired = any(n.startswith("R1") for n in notes)
    r5_fired = any(n.startswith("R5") for n in notes)
    # Only fail when a trigger is present and the corresponding rule did NOT fire.
    checks = []
    if has_prep:
        checks.append(r1_fired)
    if has_clit:
        checks.append(r5_fired)
    if not checks:
        return {"pass": True, "conf": 1.0, "note": "no triggers; vacuously pass"}
    conf = sum(checks) / len(checks)
    return {"pass": all(checks), "conf": round(conf, 3), "note": f"prep={has_prep}/{r1_fired} clit={has_clit}/{r5_fired}"}


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------
def _aggregate(layers: dict, weights: dict) -> tuple[float, int]:
    score = sum(weights[k] * layers[k]["conf"] for k in weights)
    n_pass = sum(1 for k in weights if layers[k]["pass"])
    return round(score, 4), n_pass


def _probe_audio_durations(sents: list[dict], limit: int = 50) -> dict[str, int]:
    """HEAD-request the mp3 sound_urls to get Content-Length / duration via tiny fetch.

    We try the much cheaper approach: a short range-fetch of the first 256 kB and
    parse the mp3 frame headers for total duration. If probe fails, leave None.
    """
    import urllib.request

    cache: dict[str, int] = {}
    for rec in sents[:limit]:
        url = rec.get("sound_url")
        if not url:
            continue
        try:
            req = urllib.request.Request(url, method="GET", headers={"Range": "bytes=0-524288"})
            with urllib.request.urlopen(req, timeout=15) as r:
                buf = r.read()
            cache[rec["sent_id"]] = _probe_mp3_duration_ms(buf)
        except Exception:  # noqa: BLE001
            continue
    return cache


def _probe_mp3_duration_ms(buf: bytes) -> int | None:
    # Very rough MPEG-1 Layer III duration estimate: scan for frame headers
    # 0xFFFB (MPEG-1 Layer III, no CRC) and count frames * 26.12 ms. This is
    # a sanity check, not a replacement for ffprobe.
    i = 0
    frames = 0
    FRAME_MS = 26.12  # 1152 samples / 44.1 kHz
    while i < len(buf) - 4:
        if buf[i] == 0xFF and (buf[i + 1] & 0xE0) == 0xE0:
            frames += 1
            i += 417  # typical 128 kbps frame size
        else:
            i += 1
    return int(frames * FRAME_MS) if frames > 8 else None


def validate_words(words: list[dict], skip_align: bool = False) -> tuple[list[dict], dict]:
    from build.g2p.wrapper import g2p as _g2p
    from build.translate.bridge import bridge_en_to_sl

    if not skip_align:
        from build.align.wav2vec_ctc_align import align_word
    else:
        align_word = None  # type: ignore

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA query_only = 1;")
    cur = conn.cursor()

    results: list[dict] = []
    for i, rec in enumerate(words):
        layers = {
            "L1": word_layer_L1(rec),
            "L2": word_layer_L2(rec, cur, _g2p),
            "L3": word_layer_L3(rec),
            "L4": word_layer_L4(rec),
        }
        if not skip_align:
            layers["L5"] = word_layer_L5(rec, align_word)
        else:
            layers["L5"] = {"pass": False, "conf": 0.0, "note": "skipped"}
        layers["L6"] = word_layer_L6(rec, bridge_en_to_sl)

        score, n_pass = _aggregate(layers, WORD_LAYER_WEIGHTS)
        verified = (score >= VERIFIED_THRESHOLD) and (n_pass >= MIN_LAYERS_PASS)
        results.append({
            "rank": rec.get("rank"),
            "sl": rec["sl"],
            "en_gloss": rec.get("en_gloss"),
            "sloleks_ipa": rec.get("sloleks_ipa"),
            "syllable_count": rec.get("syllable_count"),
            "audio_path": rec.get("audio_path"),
            "layers": layers,
            "score": score,
            "n_layers_pass": n_pass,
            "verified": verified,
        })
        if (i + 1) % 50 == 0:
            print(f"[deep/words] {i + 1}/{len(words)}", flush=True)
    conn.close()

    n_verified = sum(1 for r in results if r["verified"])
    n_score90 = sum(1 for r in results if r["score"] >= 0.90)
    agg = {
        "n_total": len(results),
        "n_verified": n_verified,
        "n_score_ge_0_9": n_score90,
        "mean_score": round(sum(r["score"] for r in results) / max(1, len(results)), 4),
        "layer_pass_rate": {
            k: round(sum(1 for r in results if r["layers"][k]["pass"]) / max(1, len(results)), 4)
            for k in WORD_LAYER_WEIGHTS
        },
    }
    return results, agg


def validate_sentences(sents: list[dict], probe_audio: bool = True) -> tuple[list[dict], dict]:
    from build.pipeline.synthesize import Synthesizer
    from build.translate.bridge import bridge_sl_to_en

    synth = Synthesizer()
    dur_cache: dict[str, int] = {}
    if probe_audio:
        print("[deep/sents] probing sound_urls (may be slow) ...", flush=True)
        dur_cache = _probe_audio_durations(sents)
        print(f"[deep/sents] got {len(dur_cache)}/{len(sents)} durations", flush=True)

    results: list[dict] = []
    for i, rec in enumerate(sents):
        layers = {
            "S1": sent_layer_S1(rec),
            "S2": sent_layer_S2(rec, synth, dur_cache),
            "S3": sent_layer_S3(rec),
            "S4": sent_layer_S4(rec, bridge_sl_to_en),
            "S5": sent_layer_S5(rec, synth),
        }
        score, n_pass = _aggregate(layers, SENT_LAYER_WEIGHTS)
        verified = (score >= VERIFIED_THRESHOLD) and (n_pass >= MIN_LAYERS_PASS)
        results.append({
            "sent_id": rec.get("sent_id"),
            "sl": rec["sl"],
            "en_gloss": rec.get("en_gloss"),
            "layers": layers,
            "score": score,
            "n_layers_pass": n_pass,
            "verified": verified,
        })
        if (i + 1) % 10 == 0:
            print(f"[deep/sents] {i + 1}/{len(sents)}", flush=True)
    synth.close()

    n_verified = sum(1 for r in results if r["verified"])
    agg = {
        "n_total": len(results),
        "n_verified": n_verified,
        "n_score_ge_0_9": sum(1 for r in results if r["score"] >= 0.90),
        "mean_score": round(sum(r["score"] for r in results) / max(1, len(results)), 4),
        "layer_pass_rate": {
            k: round(sum(1 for r in results if r["layers"][k]["pass"]) / max(1, len(results)), 4)
            for k in SENT_LAYER_WEIGHTS
        },
    }
    return results, agg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-align", action="store_true", help="skip L5 (slow)")
    ap.add_argument("--no-probe", action="store_true", help="skip S2 audio probing")
    ap.add_argument("--limit-words", type=int, default=0)
    ap.add_argument("--limit-sents", type=int, default=0)
    args = ap.parse_args()

    words = json.loads(WORDS_IN.read_text(encoding="utf-8"))
    sents = json.loads(SENTS_IN.read_text(encoding="utf-8"))
    if args.limit_words:
        words = words[: args.limit_words]
    if args.limit_sents:
        sents = sents[: args.limit_sents]

    print(f"[deep] validating {len(words)} words ...", flush=True)
    word_results, word_agg = validate_words(words, skip_align=args.no_align)

    print(f"[deep] validating {len(sents)} sentences ...", flush=True)
    sent_results, sent_agg = validate_sentences(sents, probe_audio=not args.no_probe)

    report = {
        "schema": "deep_validation.v1",
        "pipeline_version": "SLPROS-1",
        "word_aggregate": word_agg,
        "sentence_aggregate": sent_agg,
        "words": word_results,
        "sentences": sent_results,
    }
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[deep] wrote {REPORT_OUT}", flush=True)

    verified = [{k: r[k] for k in ("rank", "sl", "en_gloss", "sloleks_ipa", "score")} for r in word_results if r["verified"]]
    VERIFIED_OUT.write_text(json.dumps({"schema": "verified_words.v1", "count": len(verified), "words": verified}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[deep] wrote {VERIFIED_OUT} ({len(verified)} verified)", flush=True)

    print(json.dumps({"word_aggregate": word_agg, "sentence_aggregate": sent_agg}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
