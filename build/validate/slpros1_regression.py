"""SLPROS-1 scientific regression test.

For each UD-SST sentence with an aligned audio clip, we:

  1. Look up each token's IPA in ``master.sqlite`` by (surface, pos)
  2. Generate the SLPROS-1 output (with CPT prior blended in)
  3. Convert predicted syllable ``dur_rel`` → predicted token duration in seconds
     (baseline 0.18 s × n_syllables × mean dur_rel)
  4. Compare against the observed token duration from the char-CTC alignment
     (sum of char spans for the token, positional matching like cpt_learner)
  5. Aggregate: per-token and per-sentence RMSE, MAE, Pearson correlation, bias

This is the **scientific gate** that proves SLPROS-1 predicts real durations.
Results land in ``build/_slpros1_regression.json`` and get merged into
``data/validation_report.json`` under the ``slpros1_regression`` key.

Usage::

    python -m build.validate.slpros1_regression --limit 500
    python -m build.validate.slpros1_regression           # all sentences
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from build.normalize.syllabify import syllabify
from build.prosody.contour_model import build_slpros1
from build.prosody.cpt_prior import load_prior
from build.prosody.sandhi import SentenceTokens, Token

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "build" / "master.sqlite"
ALIGN_PATH = ROOT / "build" / "_udsst_aligned_full.jsonl"
UD_DIR = ROOT / "sources" / "ud_sst"
OUT_PATH = ROOT / "build" / "_slpros1_regression.json"

VOWELS = set("aeiouəɛɔɪʊɑɐɜɨʉyøœæ")


def _n_syllables(form: str) -> int:
    """Cheap orthographic syllable count for Slovene: vowel clusters ≈ syllables."""
    s = unicodedata.normalize("NFC", form.lower())
    # strip accent diacritics to count base vowels only
    n = 0
    prev_vow = False
    for ch in s:
        is_v = ch in "aeiouáéíóúàèìòùâêîôûãõ"
        if is_v and not prev_vow:
            n += 1
        prev_vow = is_v
    return max(n, 1)


def _load_conllu() -> dict[str, dict]:
    """Return ``{sent_id: {'tokens':[...], 'sound_url':..., 'text':...}}``."""
    sents: dict[str, dict] = {}
    for path in sorted(UD_DIR.glob("*.conllu")):
        with path.open(encoding="utf-8") as f:
            sid = None
            tokens: list[dict] = []
            sound_url = None
            text = None
            for ln in f:
                ln = ln.rstrip()
                if ln.startswith("# sent_id"):
                    sid = ln.split("=", 1)[1].strip()
                    tokens = []
                    sound_url = None
                    text = None
                elif ln.startswith("# sound_url"):
                    sound_url = ln.split("=", 1)[1].strip()
                elif ln.startswith("# text"):
                    text = ln.split("=", 1)[1].strip()
                elif not ln and sid:
                    sents[sid] = {"tokens": tokens, "sound_url": sound_url, "text": text}
                    sid = None
                elif sid and ln and not ln.startswith("#"):
                    parts = ln.split("\t")
                    if len(parts) < 10 or "-" in parts[0] or "." in parts[0]:
                        continue
                    tokens.append({
                        "form": parts[1],
                        "lemma": parts[2],
                        "upos": parts[3],
                        "feats": parts[5],
                        "deprel": parts[7].split(":", 1)[0],
                    })
    return sents


def _load_aligned(limit: int = 0) -> list[dict]:
    out = []
    with ALIGN_PATH.open(encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            rec = json.loads(ln)
            if rec.get("chars"):
                out.append(rec)
            if limit and len(out) >= limit:
                break
    return out


def _clip_to_sent_id(clip_path: str) -> str:
    """sources/udsst_audio/Gos018/Gos018.s305.mp3 → Gos018.s305."""
    return Path(clip_path).stem


_UPOS_PRIORITY = {
    "NOUN": ["N"],
    "PROPN": ["N"],
    "VERB": ["V"],
    "AUX": ["V"],
    "ADJ": ["A"],
    "ADV": ["R"],
    "PRON": ["P"],
    "DET": ["P"],
    "NUM": ["M"],
    "ADP": ["S"],
    "CCONJ": ["C"],
    "SCONJ": ["C"],
    "PART": ["Q"],
    "INTJ": ["I"],
}


def _best_ipa(cur: sqlite3.Cursor, form: str, upos: str) -> str | None:
    """Prefer a Sloleks word_form whose MSD first letter matches the UPOS class."""
    cur.execute(
        "SELECT surface, msd, ipa FROM word_form WHERE surface = ? AND ipa IS NOT NULL AND ipa != '' LIMIT 30",
        (form.lower(),),
    )
    rows = cur.fetchall()
    if not rows:
        # case-insensitive fallback (already lowered above, but some entries preserve case)
        cur.execute(
            "SELECT surface, msd, ipa FROM word_form WHERE surface = ? AND ipa IS NOT NULL AND ipa != '' LIMIT 30",
            (form,),
        )
        rows = cur.fetchall()
    if not rows:
        return None
    prefix_list = _UPOS_PRIORITY.get(upos, [])
    for pref in prefix_list:
        for _, msd, ipa in rows:
            if msd and msd.startswith(pref):
                return ipa
    return rows[0][2]


def _token_spans_by_form(chars: list[dict], forms: list[str]) -> list[tuple[int, int]]:
    """Scan char spans onto ordered forms (global DP-lite).

    For each form in order, we walk the char sequence left-to-right and find the
    shortest contiguous run starting at ``i`` whose characters match ≥ ``k//2``
    of the form's non-space characters (in order, allowing skips for
    alignment noise). We then record ``(i_start, i_end)`` inclusive and advance
    past the matched run. On failure we skip by 1 to try to catch the next form.
    """
    out: list[tuple[int, int]] = []
    i = 0
    n = len(chars)
    for form in forms:
        fc = [c for c in form.lower() if not c.isspace()]
        k = len(fc)
        if k == 0 or i >= n:
            out.append((-1, -1))
            continue
        threshold = max(1, k // 2)
        best: tuple[int, int, int] | None = None  # (matches, i_start, i_end)
        # try starting positions up to a small look-ahead window
        look_ahead = min(n - i, k + 6)
        for s in range(i, min(n, i + look_ahead)):
            # greedy match forward
            fi = 0
            matched = 0
            e = s
            for j in range(s, min(n, s + k + 4)):
                if fi >= k:
                    break
                if chars[j]["ch"] == fc[fi]:
                    matched += 1
                    fi += 1
                    e = j
                # soft skip: if mismatch and fi hasn't advanced for a while, allow skipping form char
                elif fi > 0 and fi < k - 1 and chars[j]["ch"] == fc[fi + 1]:
                    fi += 1  # skip one form char (deletion in audio)
                    matched += 0  # don't count as match but advance
            if matched >= threshold:
                # pick earliest viable match to keep monotonic progression
                best = (matched, s, e)
                break
        if best:
            out.append((best[1], best[2]))
            i = best[2] + 1
        else:
            out.append((-1, -1))
            i += max(1, k // 2)  # soft-skip if form unmatched
    return out


def _predict_sentence(
    tokens_ud: list[dict],
    cur: sqlite3.Cursor,
    prior,
    cpt_weight: float,
) -> tuple[list[dict], list[float]]:
    """Return (slpros1_tokens, predicted_token_durations_s). Skips PUNCT."""
    toks: list[Token] = []
    keep_idx: list[int] = []
    for i, t in enumerate(tokens_ud):
        if t["upos"] == "PUNCT":
            continue
        ipa = _best_ipa(cur, t["form"], t["upos"])
        if not ipa:
            continue
        role = "clitic" if t["upos"] in ("AUX", "ADP", "PART") and _n_syllables(t["form"]) <= 2 else "content"
        toks.append(Token(
            surface=t["form"],
            ipa=ipa,
            role=role,
            upos=t["upos"],
            deprel=t["deprel"],
        ))
        keep_idx.append(i)
    if not toks:
        return [], []
    sent = SentenceTokens(tokens=toks, register="formal")
    sp = build_slpros1(sent, contour_type="decl", cpt_prior=prior, cpt_weight=cpt_weight)
    durs: list[float] = []
    for tok in sp["tokens"]:
        total_dur_s = sum(syl["dur_rel"] * 0.18 for syl in tok["syllables"])
        durs.append(total_dur_s)
    return sp["tokens"], durs, keep_idx  # type: ignore[return-value]


def _observed_token_durations(chars: list[dict], forms: list[str]) -> list[float]:
    spans = _token_spans_by_form(chars, forms)
    out: list[float] = []
    for s, e in spans:
        if s < 0:
            out.append(float("nan"))
            continue
        dur = chars[e]["t1"] - chars[s]["t0"]
        out.append(max(0.0, dur))
    return out


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx > 0 and dy > 0 else float("nan")


def run(limit: int = 0, cpt_weight: float = 0.5) -> dict:
    sents = _load_conllu()
    aligned = _load_aligned(limit=limit)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    prior = load_prior()
    if prior is None:
        raise SystemExit("no CPT prior — run build.prosody.cpt_learner first")

    # per-token regression — both raw (absolute seconds) and rate-normalized
    pred_dur: list[float] = []
    obs_dur: list[float] = []
    pred_dur_norm: list[float] = []
    obs_dur_norm: list[float] = []
    tok_by_upos: dict[str, list[tuple[float, float]]] = defaultdict(list)
    sent_pred: list[float] = []
    sent_obs: list[float] = []
    n_sents_ok = 0
    n_sents_skipped = 0
    for clip in aligned:
        sid = _clip_to_sent_id(clip["clip"])
        ud = sents.get(sid)
        if not ud:
            n_sents_skipped += 1
            continue
        chars = clip["chars"]
        result = _predict_sentence(ud["tokens"], cur, prior, cpt_weight)
        if not result or len(result) != 3:
            n_sents_skipped += 1
            continue
        sp_tokens, pred, keep_idx = result
        if not sp_tokens:
            n_sents_skipped += 1
            continue
        forms = [ud["tokens"][i]["form"] for i in keep_idx]
        obs = _observed_token_durations(chars, forms)
        # speech-rate normalization: scale predictions so Σpred == Σobs per sentence
        valid_pairs = [(p, o, i) for p, o, i in zip(pred, obs, keep_idx) if not math.isnan(o) and o > 0 and p > 0]
        if not valid_pairs:
            continue
        sum_p = sum(p for p, _, _ in valid_pairs)
        sum_o = sum(o for _, o, _ in valid_pairs)
        rate = (sum_o / sum_p) if sum_p > 0 else 1.0
        ok = 0
        for p, o, i in valid_pairs:
            pred_dur.append(p)
            obs_dur.append(o)
            pred_dur_norm.append(p * rate)
            obs_dur_norm.append(o)
            tok_by_upos[ud["tokens"][i]["upos"]].append((p * rate, o))
            ok += 1
        if ok:
            sent_pred.append(sum(pred))
            sent_obs.append(clip["duration_s"])
            n_sents_ok += 1

    # global stats
    def _stats(xs: list[float], ys: list[float]) -> dict:
        if not xs:
            return {"n": 0}
        errs = [y - x for x, y in zip(xs, ys)]
        abs_errs = [abs(e) for e in errs]
        rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
        return {
            "n": len(xs),
            "mean_pred_s": round(sum(xs) / len(xs), 4),
            "mean_obs_s": round(sum(ys) / len(ys), 4),
            "bias_obs_minus_pred_s": round(sum(errs) / len(errs), 4),
            "mae_s": round(sum(abs_errs) / len(abs_errs), 4),
            "rmse_s": round(rmse, 4),
            "pearson_r": round(_pearson(xs, ys), 4),
        }

    token_stats_raw = _stats(pred_dur, obs_dur)
    token_stats_norm = _stats(pred_dur_norm, obs_dur_norm)
    sent_stats = _stats(sent_pred, sent_obs)
    by_upos_norm = {u: _stats([p for p, o in v], [o for p, o in v]) for u, v in tok_by_upos.items()}

    report = {
        "cpt_weight": cpt_weight,
        "n_aligned_clips_loaded": len(aligned),
        "n_sentences_ok": n_sents_ok,
        "n_sentences_skipped": n_sents_skipped,
        "per_token_raw_absolute_s": token_stats_raw,
        "per_token_rate_normalized_s": token_stats_norm,
        "per_sentence": sent_stats,
        "per_upos_rate_normalized_s": by_upos_norm,
        "interpretation": {
            "per_token_raw_absolute_s": "Evaluates absolute duration prediction (includes speaker speech-rate bias).",
            "per_token_rate_normalized_s": "Scales predictions so Sum(pred) = Sum(obs) per sentence. Isolates the relative-timing model from speaker-rate variation — this is the prosody-model gate.",
            "per_sentence": "Total sentence duration (includes inter-word pauses, not modeled here).",
        },
    }
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[regress] wrote {OUT_PATH}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="cap clips (0 = all)")
    ap.add_argument("--cpt-weight", type=float, default=0.5)
    args = ap.parse_args()
    r = run(limit=args.limit, cpt_weight=args.cpt_weight)
    print(json.dumps({
        "per_token_raw_absolute_s": r["per_token_raw_absolute_s"],
        "per_token_rate_normalized_s": r["per_token_rate_normalized_s"],
        "per_sentence": r["per_sentence"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
