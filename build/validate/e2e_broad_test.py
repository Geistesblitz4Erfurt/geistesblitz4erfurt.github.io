"""Broad end-to-end validation of the generic SL→SLPROS-1 pipeline.

Goal: prove that the deterministic, rule-based pronunciation engine degrades
**gracefully** on arbitrary Slovenian text — not just the hand-curated 151-
sentence MVP corpus — by measuring:

  * per-token IPA-resolution coverage (sloleks vs. lemma-fallback vs. grapheme
    vs. nothing)
  * sandhi rule-trigger distribution (R1–R5)
  * sentence-level SLPROS-1 success rate (fully-covered → full envelope)
  * mean tokens per sentence, distribution of contour types

The sentence pool defaults to the **UD-SST test split** (13 626 tokens,
disjoint from the UD-SST train which the CPT prior was fitted on and disjoint
from the 151-sentence MVP corpus). Using the dev/test splits as the
out-of-sample pool is a standard scientific practice: the speakers, prompts,
and registers were held out during training, so coverage on them is an
honest generalisation estimate.

A smaller EN prompt-list can also be supplied (``--en-file``) to exercise the
full EN→OPUS-MT→SL→SLPROS-1 chain.

Usage::

    # SL-only (no OPUS-MT; fast, ~2 s on 500 sentences):
    python -m build.validate.e2e_broad_test --limit 500

    # EN round-trip (slow — Marian inference):
    python -m build.validate.e2e_broad_test --en-file prompts.en.txt

Output: ``build/_e2e_broad_validation.json`` + a concise stdout summary.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from build.pipeline.synthesize import Synthesizer

ROOT = Path(__file__).resolve().parents[2]
UD_TEST = ROOT / "sources" / "ud_sst" / "sl_sst-ud-test.conllu"
UD_DEV = ROOT / "sources" / "ud_sst" / "sl_sst-ud-dev.conllu"
OUT_PATH = ROOT / "build" / "_e2e_broad_validation.json"


def _read_conllu_sentences(path: Path) -> list[str]:
    """Return a list of raw ``# text = ...`` strings from a CoNLL-U file."""
    out: list[str] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("# text = "):
            out.append(ln[len("# text = "):].strip())
    return out


def _summary(records: list[dict]) -> dict:
    total = len(records)
    if total == 0:
        return {"n_sentences": 0}
    n_full_cov = sum(1 for r in records if r["coverage"] >= 0.999)
    n_zero_cov = sum(1 for r in records if r["coverage"] < 0.001)
    n_slpros1 = sum(1 for r in records if r.get("slpros1_ok") or r.get("slpros1"))
    coverages = [r["coverage"] for r in records]
    mean_cov = sum(coverages) / total
    token_counts = [r["stats"]["n_tokens"] for r in records]
    sandhi_counts = [r["stats"]["n_sandhi_changes"] for r in records]

    source_counter: Counter[str] = Counter()
    sandhi_counter: Counter[str] = Counter()
    contour_counter: Counter[str] = Counter()
    upos_counter: Counter[str] = Counter()
    missing_counter: Counter[str] = Counter()
    total_tokens = 0
    total_resolved = 0
    for r in records:
        contour_counter[r["contour_type"]] += 1
        for t in r["tokens"]:
            total_tokens += 1
            source_counter[t["source"]] += 1
            if t.get("ipa"):
                total_resolved += 1
            else:
                missing_counter[t["surface"].lower()] += 1
            upos_counter[t["upos"]] += 1
            for note in t.get("sandhi_notes") or []:
                sandhi_counter[note.split(":")[0]] += 1

    return {
        "n_sentences": total,
        "n_sentences_full_coverage": n_full_cov,
        "n_sentences_zero_coverage": n_zero_cov,
        "n_sentences_with_slpros1": n_slpros1,
        "mean_coverage": round(mean_cov, 4),
        "mean_tokens_per_sentence": round(sum(token_counts) / total, 2),
        "mean_sandhi_triggers_per_sentence": round(sum(sandhi_counts) / total, 3),
        "total_tokens": total_tokens,
        "total_tokens_resolved": total_resolved,
        "token_resolution_rate": round(total_resolved / total_tokens, 4) if total_tokens else 0.0,
        "source_distribution": dict(source_counter),
        "sandhi_rule_triggers": dict(sandhi_counter),
        "contour_distribution": dict(contour_counter),
        "upos_distribution": dict(upos_counter.most_common(20)),
        "top_missing_tokens": dict(missing_counter.most_common(50)),
        "n_distinct_missing_tokens": len(missing_counter),
    }


def run(
    *,
    sl_sentences: list[str] | None = None,
    en_sentences: list[str] | None = None,
    limit: int = 0,
    cpt_weight: float = 0.0,
    out_path: Path = OUT_PATH,
) -> dict:
    if sl_sentences is None:
        sl_sentences = _read_conllu_sentences(UD_TEST) + _read_conllu_sentences(UD_DEV)

    if limit and sl_sentences:
        sl_sentences = sl_sentences[:limit]
    if limit and en_sentences:
        en_sentences = en_sentences[:limit]

    syn = Synthesizer(cpt_weight=cpt_weight)

    sl_records: list[dict] = []
    en_records: list[dict] = []

    t0 = time.time()
    try:
        if sl_sentences:
            for i, s in enumerate(sl_sentences):
                if i and i % 500 == 0:
                    dt = time.time() - t0
                    print(f"[e2e] sl {i}/{len(sl_sentences)} ({dt:.1f}s, {i/dt:.0f}/s)", flush=True)
                rec = syn.synthesize(s, lang="sl")
                # Strip verbose slpros1.tokens from on-disk dump — we only need the
                # stats for a summary. Keep contour_type + register top-level though.
                _slim = rec.pop("slpros1")
                rec["slpros1_ok"] = _slim is not None
                sl_records.append(rec)

        if en_sentences:
            for i, s in enumerate(en_sentences):
                if i and i % 50 == 0:
                    dt = time.time() - t0
                    print(f"[e2e] en {i}/{len(en_sentences)} ({dt:.1f}s)", flush=True)
                rec = syn.synthesize(s, lang="en")
                _slim = rec.pop("slpros1")
                rec["slpros1_ok"] = _slim is not None
                en_records.append(rec)
    finally:
        syn.close()

    report = {
        "cpt_weight": cpt_weight,
        "ud_sst_out_of_sample": {
            "summary": _summary(sl_records),
            "pool": "UD-SST dev+test (held out)",
        },
    }
    if en_records:
        report["en_round_trip"] = {
            "summary": _summary(en_records),
            "examples": en_records[:10],
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    s = report["ud_sst_out_of_sample"]["summary"]
    print(
        f"[e2e] SL pool: {s['n_sentences']} sents, "
        f"{s['n_sentences_full_coverage']} full, "
        f"token-resolution={s['token_resolution_rate']*100:.1f}%, "
        f"sandhi/sent={s['mean_sandhi_triggers_per_sentence']}, "
        f"sources={s['source_distribution']}"
    )
    if "en_round_trip" in report:
        es = report["en_round_trip"]["summary"]
        print(
            f"[e2e] EN pool: {es['n_sentences']} sents, "
            f"{es['n_sentences_full_coverage']} full, "
            f"token-resolution={es['token_resolution_rate']*100:.1f}%"
        )
    print(f"[e2e] wrote {out_path}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="cap on sentences (0 = all)")
    ap.add_argument("--cpt-weight", type=float, default=0.0)
    ap.add_argument("--en-file", type=Path, help="newline-delimited EN prompts for round-trip test")
    ap.add_argument("--sl-file", type=Path, help="override SL pool (newline-delimited)")
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args()

    sl_sents = None
    if args.sl_file:
        sl_sents = [ln.strip() for ln in args.sl_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    en_sents = None
    if args.en_file:
        en_sents = [ln.strip() for ln in args.en_file.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]

    run(
        sl_sentences=sl_sents,
        en_sentences=en_sents,
        limit=args.limit,
        cpt_weight=args.cpt_weight,
        out_path=args.out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
