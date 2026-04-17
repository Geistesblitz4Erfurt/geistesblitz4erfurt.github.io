"""SLPROS-1 duration regression against Common Voice sl.

CV clips have no UD parse, so POS is heuristically guessed (same engine as the
MVP corpus generator: surface-form rules for clitics, capitalisation, WH words).
This is a **generalisation test**: if SLPROS-1 holds up on a speaker pool that
is disjoint from UD-SST (different studio, different register, different
prompt style), the rule-based duration model is not over-fit to UD-SST.

Scoring is identical to ``slpros1_regression.py``:

  * per-token raw absolute seconds (Pearson r, MAE, RMSE, bias)
  * per-token **rate-normalised** seconds (scale predictions so Σpred == Σobs
    per clip, which removes global speech-rate variation and isolates the
    *structural* timing model — the scientific gate)

Result lands in ``build/_slpros1_cv_regression.json`` and is merged into
``data/validation_report.json`` by the compile step.

Usage::
    python -m build.validate.cv_regression --limit 0
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from pathlib import Path

from build.corpus.mvp_slpros1 import (
    _guess_upos,
    _resolve_ipa,
    _role_for,
    _contour_type,
    TOKEN_RE,
)
from build.prosody.contour_model import build_slpros1
from build.prosody.cpt_prior import load_prior
from build.prosody.sandhi import SentenceTokens, Token, apply_sandhi
from build.validate.slpros1_regression import (
    _pearson,
    _token_spans_by_form,
)

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "build" / "master.sqlite"
CV_ALIGN = ROOT / "build" / "_cv_aligned.jsonl"
OUT_PATH = ROOT / "build" / "_slpros1_cv_regression.json"

BASELINE_SYL_S = 0.18


def _load_aligned(limit: int = 0) -> list[dict]:
    out: list[dict] = []
    with CV_ALIGN.open(encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if rec.get("chars"):
                out.append(rec)
            if limit and len(out) >= limit:
                break
    return out


def _predict(cur, text: str, prior, cpt_weight: float, *, apply_sandhi_rules: bool = True):
    raw = TOKEN_RE.findall(text)
    toks: list[Token] = []
    keep: list[str] = []
    for i, surf in enumerate(raw):
        upos = _guess_upos(surf, raw[i - 1] if i > 0 else None, is_first=(i == 0))
        ipa, _src = _resolve_ipa(cur, surf, upos)
        if not ipa:
            continue
        role = _role_for(upos, surf)
        toks.append(Token(surface=surf, ipa=ipa, role=role, upos=upos, deprel=None))
        keep.append(surf)
    if not toks:
        return [], [], []
    st = SentenceTokens(tokens=toks, register="formal")
    if apply_sandhi_rules:
        apply_sandhi(st)
    sp = build_slpros1(st, contour_type=_contour_type(text), cpt_prior=prior, cpt_weight=cpt_weight)
    durs = [sum(sy["dur_rel"] * BASELINE_SYL_S for sy in tok["syllables"]) for tok in sp["tokens"]]
    return sp["tokens"], durs, keep


def _stats(pred: list[float], obs: list[float]) -> dict:
    if not pred:
        return {"n": 0}
    errs = [o - p for p, o in zip(pred, obs)]
    abs_e = [abs(e) for e in errs]
    rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
    return {
        "n": len(pred),
        "mean_pred_s": round(sum(pred) / len(pred), 4),
        "mean_obs_s": round(sum(obs) / len(obs), 4),
        "bias_obs_minus_pred_s": round(sum(errs) / len(errs), 4),
        "mae_s": round(sum(abs_e) / len(abs_e), 4),
        "rmse_s": round(rmse, 4),
        "pearson_r": round(_pearson(pred, obs), 4),
    }


def run(limit: int = 0, cpt_weight: float = 0.0, *, apply_sandhi_rules: bool = True) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA query_only = 1;")
    cur = conn.cursor()
    prior = load_prior()
    clips = _load_aligned(limit)

    pred_raw: list[float] = []
    obs_raw: list[float] = []
    pred_norm: list[float] = []
    obs_norm: list[float] = []

    n_clips_ok = 0
    n_clips_skipped = 0
    n_partial = 0

    total = len(clips)
    t_start = __import__("time").time()
    for idx_clip, clip in enumerate(clips):
        if idx_clip and idx_clip % 500 == 0:
            dt = __import__("time").time() - t_start
            print(f"[cv-regress] {idx_clip}/{total} ({dt:.1f}s, {idx_clip/dt:.1f} clips/s)", flush=True)
        text = clip.get("text") or ""
        chars = clip.get("chars") or []
        if not text or not chars:
            n_clips_skipped += 1
            continue
        sp_tokens, p_durs, forms = _predict(cur, text, prior, cpt_weight, apply_sandhi_rules=apply_sandhi_rules)
        if not forms:
            n_clips_skipped += 1
            continue

        spans = _token_spans_by_form(chars, [f.lower() for f in forms])
        o_durs: list[float] = []
        ok_idx: list[int] = []
        for idx, (s, e) in enumerate(spans):
            if s < 0 or e < 0 or e < s:
                o_durs.append(float("nan"))
                continue
            dur = chars[e]["t1"] - chars[s]["t0"]
            if dur <= 0:
                o_durs.append(float("nan"))
                continue
            o_durs.append(dur)
            ok_idx.append(idx)

        if not ok_idx:
            n_clips_skipped += 1
            continue

        if len(ok_idx) < len(forms):
            n_partial += 1

        sum_p = sum(p_durs[i] for i in ok_idx)
        sum_o = sum(o_durs[i] for i in ok_idx)
        rate = (sum_o / sum_p) if sum_p > 0 else 1.0

        for i in ok_idx:
            pred_raw.append(p_durs[i])
            obs_raw.append(o_durs[i])
            pred_norm.append(p_durs[i] * rate)
            obs_norm.append(o_durs[i])
        n_clips_ok += 1

    report = {
        "cpt_weight": cpt_weight,
        "sandhi_applied": apply_sandhi_rules,
        "n_aligned_clips_loaded": len(clips),
        "n_clips_ok": n_clips_ok,
        "n_clips_partial_span_match": n_partial,
        "n_clips_skipped": n_clips_skipped,
        "per_token_raw_absolute_s": _stats(pred_raw, obs_raw),
        "per_token_rate_normalized_s": _stats(pred_norm, obs_norm),
        "interpretation": {
            "rate_normalized": "Σpred==Σobs per clip. Isolates structural timing (the gate).",
            "gating_comparison": "UD-SST 35182-token gate was r=0.7674. If CV ≥ 0.70 the rule model generalises across corpora.",
        },
    }
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[cv-regress] clips_ok={n_clips_ok} partial={n_partial} "
        f"tokens={len(pred_raw)} r_raw={report['per_token_raw_absolute_s'].get('pearson_r')} "
        f"r_norm={report['per_token_rate_normalized_s'].get('pearson_r')}"
    )
    print(f"[cv-regress] wrote {OUT_PATH}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cpt-weight", type=float, default=0.0)
    ap.add_argument("--no-sandhi", action="store_true", help="disable sandhi cascade (A/B control)")
    args = ap.parse_args()
    run(args.limit, args.cpt_weight, apply_sandhi_rules=not args.no_sandhi)
    return 0


if __name__ == "__main__":
    sys.exit(main())
