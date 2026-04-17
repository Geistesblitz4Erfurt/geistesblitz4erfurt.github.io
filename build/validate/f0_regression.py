"""F0-contour regression: SLPROS-1 predicted cents vs observed cents.

For each UD-SST aligned clip, compute the observed F0 (in cents-from-baseline)
for each token's char span, and compare against the SLPROS-1-predicted
``f0_start_ct`` + ``f0_end_ct``. Cents are relative to the clip's 10th-percentile
Hz baseline, matching ``cpt_learner.py``.

Reports Pearson r + bias for (observed_start_ct, observed_end_ct) vs predicted.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from build.prosody.contour_model import build_slpros1
from build.prosody.cpt_prior import load_prior
from build.prosody.sandhi import SentenceTokens, Token
from build.validate.slpros1_regression import (
    _best_ipa,
    _clip_to_sent_id,
    _load_aligned,
    _load_conllu,
    _n_syllables,
    _token_spans_by_form,
    DB_PATH,
    UD_DIR,
)

ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "build" / "_slpros1_f0_regression.json"


def _hz_to_cents(hz: float, baseline: float) -> float:
    if not hz or not baseline or hz <= 0 or baseline <= 0:
        return float("nan")
    return 1200.0 * math.log2(hz / baseline)


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2:
        return float("nan")
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
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

    # global CPT means (for delta-anchor reference, applies when cpt_weight>0)
    g_f0s = (prior.global_.get("f0_start_ct") or {}).get("mean") or 0.0
    g_f0e = (prior.global_.get("f0_end_ct") or {}).get("mean") or 0.0

    pred_start: list[float] = []
    obs_start: list[float] = []
    pred_end: list[float] = []
    obs_end: list[float] = []

    n_sents = 0
    for clip in aligned:
        sid = _clip_to_sent_id(clip["clip"])
        ud = sents.get(sid)
        if not ud:
            continue
        baseline = (clip.get("f0_stats") or {}).get("baseline_hz")
        if not baseline:
            continue
        chars = clip["chars"]
        if not chars:
            continue
        # Build sentence tokens
        toks: list[Token] = []
        keep_idx: list[int] = []
        for i, t in enumerate(ud["tokens"]):
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
                deprel=t["deprel"].split(":", 1)[0],
            ))
            keep_idx.append(i)
        if not toks:
            continue
        sent = SentenceTokens(tokens=toks, register="formal")
        sp = build_slpros1(sent, contour_type="decl", cpt_prior=prior, cpt_weight=cpt_weight)

        forms = [ud["tokens"][i]["form"] for i in keep_idx]
        spans = _token_spans_by_form(chars, forms)
        for sp_tok, (s, e) in zip(sp["tokens"], spans):
            if s < 0 or e < 0 or e < s:
                continue
            # Observed: mean F0 Hz over first/last third of char span
            width = e - s + 1
            third = max(1, width // 3)
            first = [chars[k].get("f0_mean_hz") for k in range(s, s + third)]
            last = [chars[k].get("f0_mean_hz") for k in range(e - third + 1, e + 1)]
            first = [v for v in first if v and v > 0]
            last = [v for v in last if v and v > 0]
            if not first or not last:
                continue
            obs_start_hz = sum(first) / len(first)
            obs_end_hz = sum(last) / len(last)
            obs_start_ct = _hz_to_cents(obs_start_hz, baseline)
            obs_end_ct = _hz_to_cents(obs_end_hz, baseline)
            # Predicted: SLPROS-1 f0 on first/last syllable of the token
            if not sp_tok["syllables"]:
                continue
            pred_start_ct = sp_tok["syllables"][0]["f0_start_ct"]
            pred_end_ct = sp_tok["syllables"][-1]["f0_end_ct"]
            # When cpt_weight>0 the prediction is in cents-from-clip-baseline via delta
            # anchoring, which equals rule + (bucket - global). To compare against
            # obs_*_ct (cents-from-this-clip's baseline), we need the rule output on
            # the same reference. We approximate by adding the global CPT mean:
            # pred_abs_ct ~ rule + global + weighted_delta  but since rule was small
            # and we blended deltas, we just add g_f0* back as the speaker-agnostic
            # reference shift:
            pred_start_ct_abs = pred_start_ct + g_f0s
            pred_end_ct_abs = pred_end_ct + g_f0e
            pred_start.append(pred_start_ct_abs)
            obs_start.append(obs_start_ct)
            pred_end.append(pred_end_ct_abs)
            obs_end.append(obs_end_ct)
        n_sents += 1

    def _stats(xs: list[float], ys: list[float]) -> dict:
        if not xs:
            return {"n": 0}
        errs = [y - x for x, y in zip(xs, ys)]
        abs_errs = [abs(e) for e in errs]
        rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
        return {
            "n": len(xs),
            "mean_pred_ct": round(sum(xs) / len(xs), 2),
            "mean_obs_ct": round(sum(ys) / len(ys), 2),
            "bias_obs_minus_pred_ct": round(sum(errs) / len(errs), 2),
            "mae_ct": round(sum(abs_errs) / len(abs_errs), 2),
            "rmse_ct": round(rmse, 2),
            "pearson_r": round(_pearson(xs, ys), 4),
        }

    report = {
        "cpt_weight": cpt_weight,
        "n_sentences_scored": n_sents,
        "f0_start_ct": _stats(pred_start, obs_start),
        "f0_end_ct": _stats(pred_end, obs_end),
        "notes": "Pred in cents-from-baseline after adding global CPT mean (speaker-agnostic reference); obs in cents-from-clip's 10th-pct F0.",
    }
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[f0-regress] wrote {OUT_PATH}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cpt-weight", type=float, default=0.5)
    args = ap.parse_args()
    r = run(limit=args.limit, cpt_weight=args.cpt_weight)
    print(json.dumps({k: v for k, v in r.items() if k != "notes"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
