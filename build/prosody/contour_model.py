"""Deterministic SLPROS-1 generator.

Input: an ordered list of Token objects (surface + IPA + role) plus sentence-level metadata
       (contour_type, register, baseline_f0_hz).
Output: a dict conforming to build/prosody/slpros1_schema.json.

The mapping is fully rule-based and uses only:

  * The phoneme/accent data supplied with each token (IPA, accent_class, stress_syllable_idx).
  * The position of the token inside the sentence (initial/medial/pre_final/final).
  * The sentence contour type (decl, q_yn, q_wh, excl, neutral).
  * The sandhi-derived clitic/pause information on each token.

No statistical model. Every output value derives from a small set of numeric tables plus
composition rules, documented in docs/PROSODY_RULES.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from build.normalize.accent_decoder import detect_from_ipa, primary_stress_index
from build.normalize.syllabify import syllabify
from build.prosody.sandhi import SentenceTokens, Token

# Duration multipliers relative to a 180 ms baseline.
# Values empirically tuned against 35 182 aligned UD-SST tokens (see
# data/validation_report.json::slpros1_regression). DUR_CLITIC was raised from
# 0.60 → 0.85 after the sweep showed AUX/ADP predictions systematically 50 ms
# too short relative to observed.
DUR_LONG_STRESSED = 1.35
DUR_LONG_UNSTRESSED = 1.10
DUR_SHORT_STRESSED = 1.00
DUR_SHORT_UNSTRESSED = 0.75
DUR_CLITIC = 0.85
DUR_PREPAUSAL_MULTIPLIER = 1.15
DUR_BASELINE_MS = 180

# F0 envelopes per stressed-syllable accent class (cents relative to speaker baseline).
# L/S are tone-unknown classes used when Sloleks dynamic accentuation lacks tonal info.
# Their envelope averages the rising/falling case to minimize divergence from both.
STRESSED_F0 = {
    "RL": (10, 50),
    "FL": (40, -40),
    "RS": (10, 25),
    "FS": (25, -15),
    "L":  (25, 5),    # avg of RL/FL — minimally committed
    "S":  (15, 5),    # avg of RS/FS
}

# F0 envelopes for unstressed syllables by position relative to the stressed one.
UNSTRESSED_F0_BEFORE = (-5, 0)
UNSTRESSED_F0_AFTER = (0, -10)
UNSTRESSED_F0_ISOLATED = (-5, -5)

# Sentence-final contour adjustments (applied to the final and pre-final syllables).
CONTOUR_FINAL_SHIFT = {
    "decl": {"pre_final_shift_ct": -30, "final_shift_ct": -80},
    "q_yn": {"pre_final_shift_ct": 35, "final_shift_ct": 90},
    "q_wh": {"pre_final_shift_ct": -15, "final_shift_ct": -25},
    "excl": {"pre_final_shift_ct": 20, "final_shift_ct": -80},
    "neutral": {"pre_final_shift_ct": 0, "final_shift_ct": 0},
}

DEFAULT_BASELINE_HZ = 180.0  # neutral speaker, unisex mid


@dataclass
class TokenProsody:
    surface: str
    ipa: str
    role: str
    stress_syllable_idx: int
    accent_class: str
    syllables: list[dict[str, Any]]
    pause_after_ms: int = 0
    f0_contour_tag: str = "medial"


def _dur_for(length: str, stressed: bool, role: str) -> float:
    if role == "clitic":
        return DUR_CLITIC
    if length == "L":
        return DUR_LONG_STRESSED if stressed else DUR_LONG_UNSTRESSED
    return DUR_SHORT_STRESSED if stressed else DUR_SHORT_UNSTRESSED


def _syllable_length(syll_ipa: str) -> str:
    return "L" if "ː" in syll_ipa else "S"


def _tone_for(accent_class: str) -> str:
    if accent_class in ("RL", "RS"):
        return "R"
    if accent_class in ("FL", "FS"):
        return "F"
    return "-"


def _position_tag(token_index: int, total: int) -> str:
    if total == 1:
        return "isolated"
    if token_index == 0:
        return "initial"
    if token_index == total - 1:
        return "final"
    if token_index == total - 2:
        return "pre_final"
    return "medial"


def _build_syllables(ipa: str, role: str, stress_idx: int, accent_class: str) -> list[dict[str, Any]]:
    sylls = syllabify(ipa) or [ipa]
    out: list[dict[str, Any]] = []
    for i, sy in enumerate(sylls):
        length = _syllable_length(sy)
        stressed = (i == stress_idx) and role != "clitic" and accent_class != "-"
        dur_rel = _dur_for(length, stressed, role)
        if stressed:
            f0_start, f0_end = STRESSED_F0.get(accent_class, UNSTRESSED_F0_ISOLATED)
        else:
            if stress_idx < 0 or accent_class == "-":
                f0_start, f0_end = UNSTRESSED_F0_ISOLATED
            elif i < stress_idx:
                f0_start, f0_end = UNSTRESSED_F0_BEFORE
            else:
                f0_start, f0_end = UNSTRESSED_F0_AFTER
        out.append(
            {
                "phon": sy,
                "length": length,
                "tone": _tone_for(accent_class) if stressed else "-",
                "dur_rel": round(dur_rel, 3),
                "f0_start_ct": float(f0_start),
                "f0_end_ct": float(f0_end),
                "is_stressed": stressed,
            }
        )
    return out


def _apply_sentence_contour(tokens: list[TokenProsody], contour_type: str) -> None:
    """Overlay sentence-level final-contour offsets on the last two syllables of the last token."""
    shifts = CONTOUR_FINAL_SHIFT.get(contour_type, CONTOUR_FINAL_SHIFT["neutral"])
    if not tokens:
        return
    final_tok = tokens[-1]
    if not final_tok.syllables:
        return
    final_syll = final_tok.syllables[-1]
    final_syll["f0_end_ct"] += shifts["final_shift_ct"]
    final_syll["f0_start_ct"] += shifts["final_shift_ct"] * 0.5
    if len(final_tok.syllables) >= 2:
        pre = final_tok.syllables[-2]
        pre["f0_end_ct"] += shifts["pre_final_shift_ct"]
    # pre-pausal lengthening on final syllable
    final_syll["dur_rel"] = round(final_syll["dur_rel"] * DUR_PREPAUSAL_MULTIPLIER, 3)


def build_token_prosody(token: Token, token_index: int, total_tokens: int) -> TokenProsody:
    accent_class = detect_from_ipa(token.ipa)
    stress_idx = primary_stress_index(token.ipa)
    if token.role == "clitic":
        accent_class = "-"
        stress_idx = -1
    syllables = _build_syllables(token.ipa, token.role, stress_idx, accent_class)
    return TokenProsody(
        surface=token.surface,
        ipa=token.ipa,
        role=token.role,
        stress_syllable_idx=stress_idx,
        accent_class=accent_class,
        syllables=syllables,
        pause_after_ms=token.pause_after_ms,
        f0_contour_tag=_position_tag(token_index, total_tokens),
    )


def _pos_bin(i: int, total: int) -> str:
    if total == 1:
        return "solo"
    if i == 0:
        return "initial"
    if i == total - 1:
        return "final"
    if i == total - 2:
        return "penult"
    return "medial"


def _blend_cpt_prior(
    sent: SentenceTokens,
    tokens_out: list[dict[str, Any]],
    prior,
    *,
    weight: float = 0.5,
    min_n: int = 20,
) -> None:
    """Blend empirical (upos, deprel, pos_bin) CPT prior into the rule-based output.

    The CPT was learned in cents-from-clip-baseline space, so absolute bucket means
    sit ~400 ct above zero (per-clip 10th-percentile F0 lies ~4 semitones below the
    clip mean). The rule output, in contrast, uses cents-from-speaker-baseline with
    values around 0. To make the two compatible we convert the prior to **deltas
    from the global CPT mean**, then add a weighted delta to the rule output::

        f0_start_ct_final  :=  rule  +  w * (prior_bucket_mean - prior_global_mean)
        dur_rel_final      :=  (1-w) * rule  +  w * prior_bucket_mean

    Duration is bounded to a plausible physical range [0.3, 2.5] and F0 shifts to
    [-150, +150] ct to cap pathological small-sample buckets.
    """
    glob = prior.global_ or {}
    g_dur = (glob.get("dur_rel") or {}).get("mean") or 1.0
    g_f0s = (glob.get("f0_start_ct") or {}).get("mean") or 0.0
    g_f0e = (glob.get("f0_end_ct") or {}).get("mean") or 0.0

    total = len(sent.tokens)
    for i, (tok, out) in enumerate(zip(sent.tokens, tokens_out)):
        upos = getattr(tok, "upos", None)
        deprel = getattr(tok, "deprel", None)
        if not upos:
            continue
        entry = prior.lookup(upos=upos, deprel=deprel, pos_bin=_pos_bin(i, total), min_n=min_n)
        if not entry:
            continue
        dur_mean = (entry.get("dur_rel") or {}).get("mean")
        f0s_mean = (entry.get("f0_start_ct") or {}).get("mean")
        f0e_mean = (entry.get("f0_end_ct") or {}).get("mean")
        d_f0s = (float(f0s_mean) - g_f0s) if f0s_mean is not None else 0.0
        d_f0e = (float(f0e_mean) - g_f0e) if f0e_mean is not None else 0.0
        for syl in out["syllables"]:
            if dur_mean is not None:
                blended = (1 - weight) * syl["dur_rel"] + weight * float(dur_mean)
                syl["dur_rel"] = round(max(0.3, min(2.5, blended)), 3)
            if f0s_mean is not None:
                syl["f0_start_ct"] = round(syl["f0_start_ct"] + weight * max(-150.0, min(150.0, d_f0s)), 2)
            if f0e_mean is not None:
                syl["f0_end_ct"] = round(syl["f0_end_ct"] + weight * max(-150.0, min(150.0, d_f0e)), 2)
        out["cpt_prior_applied"] = True


def build_slpros1(
    sent: SentenceTokens,
    *,
    contour_type: str = "decl",
    baseline_f0_hz: float = DEFAULT_BASELINE_HZ,
    final_pause_ms: int = 500,
    cpt_prior=None,
    cpt_weight: float = 0.0,  # regression sweep on 35182 UD-SST tokens chose pure rule; see data/validation_report.json
) -> dict[str, Any]:
    total = len(sent.tokens)
    token_prosody = [build_token_prosody(t, i, total) for i, t in enumerate(sent.tokens)]
    _apply_sentence_contour(token_prosody, contour_type)

    tokens_out = [
        {
            "surface": tp.surface,
            "ipa": tp.ipa,
            "role": tp.role,
            "stress_syllable_idx": tp.stress_syllable_idx,
            "accent_class": tp.accent_class,
            "syllables": tp.syllables,
            "pause_after_ms": tp.pause_after_ms,
            "f0_contour_tag": tp.f0_contour_tag,
            "audio_asset_id": None,
        }
        for tp in token_prosody
    ]

    if cpt_prior is not None:
        _blend_cpt_prior(sent, tokens_out, cpt_prior, weight=cpt_weight)

    return {
        "version": "SLPROS-1",
        "contour_type": contour_type,
        "register": sent.register,
        "baseline_f0_hz": baseline_f0_hz,
        "tokens": tokens_out,
        "final_pause_ms": final_pause_ms,
        "cpt_prior_source": (cpt_prior.meta if cpt_prior else None),
    }
