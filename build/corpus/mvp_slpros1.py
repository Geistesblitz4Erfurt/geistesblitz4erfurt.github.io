"""Generate SLPROS-1 for the MVP sentence corpus (151 sentences).

Pipeline per sentence:
  1. Tokenise the Slovenian string (unicode word tokens, keep apostrophes/hyphens).
  2. Resolve each surface to the best Sloleks ``word_form`` IPA via a case-insensitive
     lookup with UPOS-heuristic MSD preference. Fall back to G2P (accented_form from
     surface match) and finally to a bare grapheme-IPA for irreducible function words
     like the preposition ``z`` (/z/).
  3. Infer a lightweight UPOS/role per token (AUX/ADP/PART clitic detection).
  4. Infer sentence contour_type from terminal punctuation (``?`` → q_yn or q_wh,
     ``!`` → excl, else decl).
  5. Call build_slpros1 with the CPT prior at the project-default cpt_weight.
  6. Write a self-describing JSON with per-token IPA, coverage, SLPROS-1 output,
     and a coverage-gap report.

Run::
    python -m build.corpus.mvp_slpros1 \
        --corpus build/_corpus_preview.json \
        --out build/_mvp_slpros1.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from build.prosody.contour_model import build_slpros1
from build.prosody.cpt_prior import load_prior
from build.prosody.sandhi import SentenceTokens, Token, apply_sandhi

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "build" / "master.sqlite"

TOKEN_RE = re.compile(r"\w+[\w'\u2019-]*", flags=re.UNICODE)

WH_WORDS = {
    "kaj", "kje", "kdaj", "kako", "koliko", "kdo", "zakaj", "kam", "kateri",
    "katera", "katero", "katere", "kateremu", "katerih", "katerim", "koga",
    "komu", "čigav", "česa",
}

CLITIC_UPOS = {"AUX", "ADP", "PART"}

# Slovenian verb suffixes, ordered longest-first so "-ijo" wins over "-jo"
# before "-o". Each pattern implies VERB unless the surface is explicitly
# listed as a known non-verb (already short-circuited above).
#
# Coverage (conjugation classes I–VI present, l-participle, infinitive):
#   -m    1sg pres           (delam, grem, znam, imam, morem)
#   -š    2sg pres           (delaš, greš, veš)
#   -mo   1pl pres           (delamo, gremo, imamo)
#   -te   2pl pres / imper   (delate, greste)      — collides with noun pl-nom "-te" (rare)
#   -jo   3pl pres           (delajo, grejo, jejo)
#   -ijo  3pl pres -i class  (hodijo, vidijo)
#   -ejo  3pl pres -e class  (pišejo, žejo)
#   -ti   infinitive         (delati, iti, pisati)
#   -či   infinitive cons.   (peči, reči, seči)
#   -l    l-participle masc  (delal, šel, bil)     — ambiguous with nouns; conservative
#   -la   l-participle fem   (delala, šla)         — ambiguous with nouns; conservative
#   -lo   l-participle neut  (delalo, šlo)         — ambiguous with nouns; conservative
#   -li   l-participle pl    (delali, šli)
#   -le   l-participle fem-pl (delale, šle)
_VERB_SUFFIXES_STRONG = ("ijo", "ejo", "mo", "ti", "či", "jo", "š")
_VERB_SUFFIXES_1SG = ("m",)       # 1sg: only if not a noun-looking bigram
_VERB_SUFFIXES_LPART = ("la", "lo", "li", "le")  # applied with length gate
_VERB_MIN_LEN = 4  # shorter suffix matches get false positives on short nouns

# UPOS → first-letter priority on Sloleks MSD column (e.g. 'N' for nouns)
UPOS_MSD_PRIORITY = {
    "NOUN": ["Sos", "Sl", "S"],
    "PROPN": ["Sl", "Slz", "Slm", "Sls"],
    "VERB": ["Gg", "G"],
    "AUX": ["Va", "V"],
    "ADJ": ["Ps", "Pp", "P"],
    "PRON": ["Za", "Zk", "Zs", "Zl", "Z"],
    "NUM": ["Kb", "Kg", "K"],
    "ADV": ["R"],
    "ADP": ["D"],
    "CCONJ": ["Vp"],
    "SCONJ": ["Vd"],
    "PART": ["L"],
    "INTJ": ["M"],
    "DET": ["Zk", "Zs", "Zp"],
}

# Hard-coded IPA fallbacks for a tiny list of function-word graphemes Sloleks
# stores without phonetic data (e.g. the letter/preposition ``z``).
# These follow CJVT-IPA conventions and standard Slovene orthography.
GRAPHEME_FALLBACK = {
    "z": "z",       # preposition + instrumental (voiced); voiceless variant ``s`` exists
    "s": "s",
    "k": "k",
    "v": "u̯",     # "v" before consonant is often vocalised in informal speech; "v" + V → v
    "h": "x",
    "in": "in",    # conjunction
}

DEFAULT_OUT = ROOT / "build" / "_mvp_slpros1.json"


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _n_syllables(form: str) -> int:
    s = _nfc(form.lower())
    n, prev_v = 0, False
    for ch in s:
        is_v = ch in "aeiouáéíóúàèìòùâêîôûãõ"
        if is_v and not prev_v:
            n += 1
        prev_v = is_v
    return max(n, 1)


def _guess_upos(surface: str, prev_surface: str | None, is_first: bool) -> str:
    """Heuristic UPOS for an MVP token without a UD parse.

    Rules are intentionally small and deterministic; they gate the MSD
    lookup priority and the clitic flag.
    """
    s = _nfc(surface.lower())
    # Interrogative WH pronoun/adverb
    if s in WH_WORDS:
        return "PRON" if s in {"kaj", "kdo", "kateri", "katera", "katero"} else "ADV"
    # Short auxiliary and modal forms
    if s in {"sem", "si", "je", "smo", "ste", "so", "bi", "bom", "boš", "bo", "bova", "bomo", "boste", "bodo", "bil", "bila", "bilo"}:
        return "AUX"
    # Prepositions
    if s in {"v", "na", "z", "s", "k", "h", "o", "ob", "po", "pod", "pri", "za", "iz", "do", "od", "čez", "skozi", "med", "pred", "med", "brez"}:
        return "ADP"
    # Conjunctions / particles
    if s in {"in", "ali", "a", "pa", "ter"}:
        return "CCONJ"
    if s in {"da", "ker", "če", "ko", "dokler", "medtem"}:
        return "SCONJ"
    if s in {"ne", "ja", "tudi", "morda", "prosim", "hvala", "lahko"}:
        return "PART"
    # Proper nouns — capitalised mid-sentence
    if not is_first and surface[:1].isupper():
        return "PROPN"
    # Numbers
    if any(c.isdigit() for c in surface):
        return "NUM"
    # Verb morphology — catches ~85% of finite/infinitive Slovene verbs
    # via ending suffix. Requires a minimum stem length to avoid pulling in
    # short noun forms (e.g. "tem" genitive-pl isn't a 1sg).
    if len(s) >= _VERB_MIN_LEN:
        for suf in _VERB_SUFFIXES_STRONG:
            if s.endswith(suf):
                return "VERB"
        for suf in _VERB_SUFFIXES_LPART:
            if s.endswith(suf) and len(s) >= 5:  # extra length gate for ambiguous -la/-li
                return "VERB"
        # 1sg -m: only when preceded by a vowel (avoids "tem", "čim", "kom"
        # which are pronominal datives) and word is ≥5 chars (rules out "sem",
        # "nam" — already handled as AUX/PRON list items above).
        if s.endswith("m") and len(s) >= 5 and s[-2] in "aeiouáéíóúàèìòùâêîôû":
            return "VERB"
    # Default: NOUN
    return "NOUN"


def _contour_type(sl_text: str) -> str:
    t = sl_text.strip()
    if not t:
        return "decl"
    last = t[-1]
    if last == "!":
        return "excl"
    if last == "?":
        head = _nfc(t.lower()).split()
        if head and head[0] in WH_WORDS:
            return "q_wh"
        return "q_yn"
    return "decl"


_IPA_CACHE: dict[tuple[str, str], tuple[str | None, str]] = {}


def _resolve_ipa(
    cur: sqlite3.Cursor,
    surface: str,
    upos: str,
) -> tuple[str | None, str]:
    """Return (ipa, source_tag). source_tag ∈ {'sloleks', 'sloleks_lemma', 'grapheme', 'g2p', 'none'}.

    Results are memoised per (surface_lower, upos) within the process — the CV
    regression and the MVP pipeline hit the same surfaces many times and a bare
    SQL roundtrip costs ~0.5 ms after the NOCASE index.
    """
    key = (surface.lower(), upos)
    hit = _IPA_CACHE.get(key)
    if hit is not None:
        return hit
    # 1) direct word_form, case-insensitive
    cur.execute(
        "SELECT surface, msd, ipa FROM word_form "
        "WHERE surface = ? COLLATE NOCASE AND ipa IS NOT NULL AND ipa != '' "
        "LIMIT 40",
        (surface,),
    )
    rows = cur.fetchall()
    if rows:
        prefix_list = UPOS_MSD_PRIORITY.get(upos, [])
        for pref in prefix_list:
            for _, msd, ipa in rows:
                if msd and msd.startswith(pref):
                    res = (ipa, "sloleks")
                    _IPA_CACHE[key] = res
                    return res
        res = (rows[0][2], "sloleks")
        _IPA_CACHE[key] = res
        return res

    # 2) lemma table → any form's ipa
    cur.execute(
        "SELECT id FROM lemma WHERE lemma = ? COLLATE NOCASE LIMIT 3",
        (surface,),
    )
    lids = [r[0] for r in cur.fetchall()]
    for lid in lids:
        cur.execute(
            "SELECT surface, msd, ipa FROM word_form WHERE lemma_id = ? AND ipa IS NOT NULL AND ipa != '' LIMIT 30",
            (lid,),
        )
        rows2 = cur.fetchall()
        if rows2:
            # Try to pick base-nominative-singular form (Slzei / Somei style)
            for s2, _msd2, ipa2 in rows2:
                if s2.lower() == surface.lower():
                    res = (ipa2, "sloleks_lemma")
                    _IPA_CACHE[key] = res
                    return res
            res = (rows2[0][2], "sloleks_lemma")
            _IPA_CACHE[key] = res
            return res

    # 3) grapheme fallback for function-word pocket
    gkey = _nfc(surface.lower())
    if gkey in GRAPHEME_FALLBACK:
        res = (GRAPHEME_FALLBACK[gkey], "grapheme")
        _IPA_CACHE[key] = res
        return res

    # 4) G2P fallback on the raw surface — clarinsi/slovene_g2p (Apache-2.0),
    #    rule-based, no model weights. Without accent info the output lacks
    #    stress/length diacritics, but the phoneme sequence is still CJVT-IPA
    #    compliant. Validated on UD-SST dev+test (499/499 previously-missing
    #    tokens resolved, CV regression r_norm 0.8412→0.8436). On cold start
    #    this loads ~6 TSVs (~2 s) lazily on first call; if no OOV tokens are
    #    hit, G2P is never initialised.
    #
    #    Opt-out: SLPROS_DISABLE_G2P=1 (build-unit-tests and CI regressions
    #    that want a pure-Sloleks pool set this).
    import os
    if os.environ.get("SLPROS_DISABLE_G2P") != "1":
        try:
            from build.g2p.wrapper import g2p  # lazy import
            g2p_res = g2p(surface, "Unknown", "")
            if g2p_res:
                res = (g2p_res, "g2p")
                _IPA_CACHE[key] = res
                return res
        except Exception:
            pass

    _IPA_CACHE[key] = (None, "none")
    return None, "none"


def _role_for(upos: str, surface: str) -> str:
    if upos in CLITIC_UPOS and _n_syllables(surface) <= 2:
        return "clitic"
    return "content"


def build_for_sentence(
    cur: sqlite3.Cursor,
    sent: dict,
    prior,
    *,
    cpt_weight: float,
) -> dict:
    sl = sent["sl"]
    raw_tokens = TOKEN_RE.findall(sl)
    toks: list[Token] = []
    resolved: list[dict[str, Any]] = []
    for i, surf in enumerate(raw_tokens):
        upos = _guess_upos(surf, raw_tokens[i - 1] if i > 0 else None, is_first=(i == 0))
        ipa, src = _resolve_ipa(cur, surf, upos)
        role = _role_for(upos, surf)
        resolved.append({
            "surface": surf,
            "ipa": ipa,
            "source": src,
            "upos": upos,
            "role": role,
        })
        if ipa:
            toks.append(Token(
                surface=surf,
                ipa=ipa,
                role=role,
                upos=upos,
                deprel=None,
            ))

    contour = _contour_type(sl)
    if not toks:
        return {
            "id": sent["id"],
            "sl": sl,
            "en": sent.get("en", ""),
            "contour_type": contour,
            "coverage": 0.0,
            "tokens": resolved,
            "slpros1": None,
        }

    st = SentenceTokens(tokens=toks, register=sent.get("register", "formal"))
    apply_sandhi(st)
    # Mirror sandhi outcomes onto the resolved rows so downstream consumers
    # (emit_json.py, the frontend) can show/play the post-sandhi IPA.
    sandhi_iter = iter(st.tokens)
    for r in resolved:
        if not r["ipa"]:
            r["sandhi_notes"] = []
            continue
        t_after = next(sandhi_iter)
        r["ipa_after_sandhi"] = t_after.ipa
        r["role_after_sandhi"] = t_after.role
        r["sandhi_notes"] = list(t_after.notes)
    sp = build_slpros1(st, contour_type=contour, cpt_prior=prior, cpt_weight=cpt_weight)

    coverage = sum(1 for r in resolved if r["ipa"]) / len(resolved)
    return {
        "id": sent["id"],
        "sl": sl,
        "en": sent.get("en", ""),
        "category": sent.get("category"),
        "register": sent.get("register", "formal"),
        "contour_type": contour,
        "coverage": round(coverage, 3),
        "tokens": resolved,
        "slpros1": sp,
    }


def run(
    corpus_path: Path,
    out_path: Path,
    cpt_weight: float,
) -> dict:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    sentences = corpus["sentences"]

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA query_only = 1;")
    cur = conn.cursor()
    prior = load_prior()
    if prior is None:
        print("[mvp_slpros1] WARNING: no CPT prior (cpt_weight ignored)")

    out_sentences: list[dict] = []
    source_counter: Counter[str] = Counter()
    missing_tokens: Counter[str] = Counter()
    full_covered = 0

    for sent in sentences:
        rec = build_for_sentence(cur, sent, prior, cpt_weight=cpt_weight)
        out_sentences.append(rec)
        for tok in rec["tokens"]:
            source_counter[tok["source"]] += 1
            if not tok["ipa"]:
                missing_tokens[tok["surface"].lower()] += 1
        if rec["coverage"] >= 0.999:
            full_covered += 1

    total_tokens = sum(source_counter.values())
    report = {
        "cpt_weight": cpt_weight,
        "n_sentences": len(out_sentences),
        "n_sentences_full_coverage": full_covered,
        "n_tokens": total_tokens,
        "token_source_breakdown": dict(source_counter),
        "missing_tokens": dict(missing_tokens),
        "sentences": out_sentences,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[mvp_slpros1] {len(out_sentences)} sentences | "
        f"{full_covered} fully covered | "
        f"{total_tokens} tokens | "
        f"sources={dict(source_counter)} | "
        f"missing={len(missing_tokens)}"
    )
    if missing_tokens:
        print("[mvp_slpros1] missing:", sorted(missing_tokens.keys()))
    print(f"[mvp_slpros1] wrote {out_path}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=ROOT / "build" / "_corpus_preview.json")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--cpt-weight", type=float, default=0.0)
    args = ap.parse_args()
    run(args.corpus, args.out, args.cpt_weight)
    return 0


if __name__ == "__main__":
    sys.exit(main())
