"""Learn a conditional probability table (CPT) for SLPROS-1 from aligned speech.

Inputs:
    * ``build/_udsst_aligned.jsonl`` — char-level CTC alignment + F0 per clip
      (one JSON per line, from ``build.align.ctc_align``).
    * ``sources/ud_sst/*.conllu`` — UPOS + deprel + sent_id per token, so we can
      associate each aligned word with its syntactic context.
    * ``sources/udsst_audio/manifest.tsv`` — maps clip path → sent_id.

Method:

    1. For each aligned clip we look up the corresponding UD sentence and
       tokenise the clip's transcript on whitespace (UD tokenisation matches
       the sound_url text by construction — both come from the same treebank
       source).
    2. For each token we slice the char-spans that fall between its word
       boundaries (tracked via running character offsets + ``|`` word
       boundaries in the CTC alignment). We compute:
           - ``dur_s`` = total duration of the token (sum of char spans)
           - ``n_syl`` = syllable count (vowel cluster heuristic)
           - ``dur_rel`` = dur_s / (n_syl × baseline_syl_s)
                          where baseline_syl_s = 0.18 (SLPROS-1 canonical)
           - ``f0_start_ct`` = cents offset of first-voiced-frame F0 from the
             clip's 10th-percentile baseline
           - ``f0_end_ct``   = same for last-voiced-frame
    3. Bucket each token by ``(upos, deprel, rel_pos_bin)`` where
       ``rel_pos_bin`` ∈ {"initial","medial","penult","final"} is a 4-way
       split over (token_idx / n_tokens).
    4. Aggregate: per bucket emit ``{n, dur_rel_mean, dur_rel_std, f0_start_mean_ct,
       f0_start_std_ct, f0_end_mean_ct, f0_end_std_ct}`` and global overall stats.

Output: ``build/_prosody_cpt.json`` — the SLPROS-1 generator reads this as
prior at build time. Contains only observed (upos, deprel, pos_bin) buckets;
unseen combinations fall back to the per-upos marginal, then the global prior.

Run::

    PYTHONIOENCODING=utf-8 python -m build.prosody.cpt_learner

The learner is deterministic (no randomness). Numerical stability uses
log-f0 in cents so distributions are roughly Gaussian.
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALIGN_PATH = REPO_ROOT / "build" / "_udsst_aligned_full.jsonl"
if not ALIGN_PATH.exists():
    ALIGN_PATH = REPO_ROOT / "build" / "_udsst_aligned.jsonl"
MANIFEST_PATH = REPO_ROOT / "sources" / "udsst_audio" / "manifest.tsv"
UD_DIR = REPO_ROOT / "sources" / "ud_sst"
OUT_PATH = REPO_ROOT / "build" / "_prosody_cpt.json"

BASELINE_SYL_S = 0.18  # SLPROS-1 canonical baseline (180 ms / syllable)
VOWELS = set("aeiouəɛɔɪʊ")


def _count_syllables(word: str) -> int:
    """Crude but effective: count vowel clusters in the orthographic word."""
    w = word.lower()
    n = 0
    prev_v = False
    for ch in w:
        is_v = ch in VOWELS or ch in "áéíóúàèìòù"
        if is_v and not prev_v:
            n += 1
        prev_v = is_v
    return max(n, 1)


def _load_ud_tokens() -> dict[str, list[dict]]:
    """sent_id → list of token dicts (upos, deprel, form)."""
    out: dict[str, list[dict]] = {}
    sid_re = re.compile(r"sent_id\s*=\s*(\S+)")
    for path in sorted(UD_DIR.glob("*.conllu")):
        current_sid = None
        toks: list[dict] = []
        for ln in path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                if current_sid and toks:
                    out[current_sid] = toks
                current_sid = None
                toks = []
                continue
            if ln.startswith("#"):
                m = sid_re.search(ln)
                if m:
                    current_sid = m.group(1)
                continue
            cols = ln.split("\t")
            if len(cols) < 8 or "-" in cols[0] or "." in cols[0]:
                continue
            toks.append({"form": cols[1], "upos": cols[3], "deprel": cols[7]})
        if current_sid and toks:
            out[current_sid] = toks
    return out


def _load_manifest() -> dict[str, str]:
    """local_path (basename) → sent_id."""
    out: dict[str, str] = {}
    if not MANIFEST_PATH.exists():
        return out
    with MANIFEST_PATH.open("r", encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for ln in fh:
            parts = ln.rstrip("\n").split("\t")
            if len(parts) < len(header):
                continue
            row = dict(zip(header, parts))
            # clip basename (e.g. Gos031.s23.mp3) → sent_id
            basename = Path(row.get("local_path", "")).name
            sid = row.get("sent_id", "")
            if basename and sid:
                out[basename] = sid
    return out


def _pos_bin(idx: int, n: int) -> str:
    if n <= 1:
        return "solo"
    rel = idx / (n - 1)
    if rel == 0:
        return "initial"
    if rel == 1:
        return "final"
    if rel >= 0.75:
        return "penult"
    return "medial"


def _hz_to_cents(hz: float, baseline: float) -> float:
    if not hz or not baseline:
        return 0.0
    return 1200.0 * math.log2(hz / baseline)


def _segment_tokens(chars: list[dict], tokens: list[str]) -> list[list[dict]]:
    """Walk char spans, split on whitespace produced by the transcript.

    The CTC alignment drops punctuation and whitespace, so we re-synchronise:
    for each expected token we pop the next ``len(clean_token)`` char spans.
    """
    # clean tokens: keep only chars that appear in the CTC vocab
    keep = set("abcdefghijklmnoprstuvwxyzčšž")
    per_tok: list[list[dict]] = []
    i = 0
    for tok in tokens:
        clean = [ch for ch in tok.lower() if ch in keep]
        k = len(clean)
        if k == 0:
            per_tok.append([])
            continue
        slice_ = chars[i:i + k]
        # Positional consumption: always advance by expected length. Record the
        # slice only if at least one char matches — otherwise we consider the
        # token mis-aligned and skip feature extraction (but still consume).
        matches = sum(1 for a, b in zip(slice_, clean) if a["ch"] == b)
        if slice_ and matches >= max(1, k // 3):
            per_tok.append(slice_)
        else:
            per_tok.append([])
        i += k
    return per_tok


def _token_features(spans: list[dict], form: str, baseline_hz: float) -> dict | None:
    if not spans:
        return None
    dur_s = spans[-1]["t1"] - spans[0]["t0"]
    n_syl = _count_syllables(form)
    if dur_s <= 0 or n_syl <= 0:
        return None
    dur_rel = dur_s / (n_syl * BASELINE_SYL_S)

    f0s = [sp.get("f0_mean_hz") for sp in spans if sp.get("f0_mean_hz")]
    if not f0s or not baseline_hz:
        f0_start_ct = f0_end_ct = None
    else:
        f0_start_ct = _hz_to_cents(f0s[0], baseline_hz)
        f0_end_ct = _hz_to_cents(f0s[-1], baseline_hz)

    return {
        "dur_s": round(dur_s, 4),
        "n_syl": n_syl,
        "dur_rel": round(dur_rel, 3),
        "f0_start_ct": round(f0_start_ct, 1) if f0_start_ct is not None else None,
        "f0_end_ct": round(f0_end_ct, 1) if f0_end_ct is not None else None,
    }


def _running_stats():
    return {"n": 0, "sum": 0.0, "sq": 0.0}


def _update(stats: dict, x: float) -> None:
    stats["n"] += 1
    stats["sum"] += x
    stats["sq"] += x * x


def _finalize(stats: dict) -> dict:
    n = stats["n"]
    if n == 0:
        return {"n": 0, "mean": None, "std": None}
    mean = stats["sum"] / n
    var = max(0.0, stats["sq"] / n - mean * mean)
    return {"n": n, "mean": round(mean, 3), "std": round(math.sqrt(var), 3)}


def learn() -> dict:
    ud = _load_ud_tokens()
    print(f"[cpt] loaded {len(ud)} UD sentences", flush=True)
    mani = _load_manifest()
    print(f"[cpt] loaded {len(mani)} manifest rows", flush=True)

    if not ALIGN_PATH.exists():
        raise SystemExit(f"missing {ALIGN_PATH}")

    # bucket → feature stats
    buckets: dict[tuple[str, str, str], dict[str, dict]] = defaultdict(
        lambda: {"dur_rel": _running_stats(), "f0_start_ct": _running_stats(), "f0_end_ct": _running_stats()}
    )
    upos_marginal: dict[str, dict[str, dict]] = defaultdict(
        lambda: {"dur_rel": _running_stats(), "f0_start_ct": _running_stats(), "f0_end_ct": _running_stats()}
    )
    global_stats = {"dur_rel": _running_stats(), "f0_start_ct": _running_stats(), "f0_end_ct": _running_stats()}

    n_clips = n_matched = n_tokens = n_dropped = 0

    with ALIGN_PATH.open("r", encoding="utf-8") as fh:
        for ln in fh:
            rec = json.loads(ln)
            n_clips += 1
            if rec.get("error") or not rec.get("chars"):
                n_dropped += 1
                continue
            clip_name = Path(rec["clip"]).name
            sid = mani.get(clip_name)
            if not sid or sid not in ud:
                n_dropped += 1
                continue
            n_matched += 1

            ud_toks = ud[sid]
            # align ud_tokens to whitespace-split transcript tokens in rec["text"]
            trans_toks = rec["text"].split()
            # best case: same length. Otherwise skip.
            if len(trans_toks) != len(ud_toks):
                n_dropped += 1
                continue

            baseline_hz = (rec.get("f0_stats") or {}).get("baseline_hz") or 0.0
            token_spans = _segment_tokens(rec["chars"], trans_toks)
            n = len(trans_toks)
            for idx, (form, spans, ud_tok) in enumerate(zip(trans_toks, token_spans, ud_toks)):
                feats = _token_features(spans, form, baseline_hz)
                if feats is None:
                    continue
                n_tokens += 1
                key = (ud_tok["upos"], ud_tok["deprel"], _pos_bin(idx, n))
                for feat_name in ("dur_rel", "f0_start_ct", "f0_end_ct"):
                    v = feats.get(feat_name)
                    if v is None:
                        continue
                    _update(buckets[key][feat_name], v)
                    _update(upos_marginal[ud_tok["upos"]][feat_name], v)
                    _update(global_stats[feat_name], v)

    print(f"[cpt] clips={n_clips} matched={n_matched} dropped={n_dropped} tokens={n_tokens}", flush=True)

    def _fmt(stats_group: dict) -> dict:
        return {k: _finalize(v) for k, v in stats_group.items()}

    out = {
        "meta": {
            "n_clips": n_clips,
            "n_matched": n_matched,
            "n_tokens": n_tokens,
            "baseline_syl_s": BASELINE_SYL_S,
            "source": "UD-SST + GOS/ARTUR audio (validation-only) + wav2vec2-xls-r-sloveneASR",
        },
        "global": _fmt(global_stats),
        "by_upos": {k: _fmt(v) for k, v in upos_marginal.items()},
        "by_upos_deprel_pos": {
            f"{u}|{d}|{p}": _fmt(v) for (u, d, p), v in buckets.items()
        },
    }
    return out


def main() -> int:
    out = learn()
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[cpt] wrote {OUT_PATH}")
    print(f"[cpt] global={out['global']}")
    # show top-10 largest buckets
    items = list(out["by_upos_deprel_pos"].items())
    items.sort(key=lambda kv: -(kv[1]["dur_rel"]["n"] or 0))
    print("[cpt] top buckets:")
    for key, stats in items[:10]:
        n = stats["dur_rel"]["n"]
        dm = stats["dur_rel"]["mean"]
        fm = stats["f0_end_ct"]["mean"]
        print(f"  {key}  n={n}  dur_rel={dm}  f0_end_ct={fm}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
