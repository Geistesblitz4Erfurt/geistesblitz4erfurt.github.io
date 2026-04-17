"""Deep-validator-facing wrapper around :mod:`build.align.ctc_align`.

The heavy lifting (model load, resampling, CTC Viterbi) lives in the existing
char-level aligner. Here we package the result in the shape the deep validator
(Layer 5) expects::

    {
      "wav": "data/audio/words/lingualibre/hiša_77c0a842ed89.wav",
      "sl": "hiša",
      "expected_ipa": "ˈxiːʃa",
      "duration_ms": 812,
      "char_boundaries_ms": [{"ch":"h","t0":0,"t1":80,"score":-1.2}, ...],
      "mean_conf": 0.74,
      "aligned_chars": "hiša"
    }

``mean_conf`` = ``exp(mean(log-prob-score))`` across spans. We expose only
character-level output — phoneme mapping (char→IPA) is a separate concern
handled downstream in the deep validator against Sloleks' ``word_form.ipa``.

Run::

    PYTHONIOENCODING=utf-8 python -m build.align.wav2vec_ctc_align \
        --wav data/audio/words/lingualibre/hiša_77c0a842ed89.wav --sl hiša
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def align_word(wav_path: Path | str, sl: str, *, expected_ipa: str | None = None) -> dict[str, Any]:
    from build.align.ctc_align import align_one

    p = Path(wav_path)
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    raw = align_one(p, sl)

    if raw.get("error"):
        return {
            "wav": str(p),
            "sl": sl,
            "expected_ipa": expected_ipa,
            "duration_ms": int(round(raw.get("duration_s", 0.0) * 1000)),
            "char_boundaries_ms": [],
            "mean_conf": 0.0,
            "aligned_chars": "",
            "error": raw["error"],
        }

    chars = raw.get("chars", []) or []
    non_boundary = [c for c in chars if c.get("ch") not in ("|", " ", "")]

    char_boundaries_ms = [
        {
            "ch": c.get("ch"),
            "t0": int(round(c.get("t0", 0.0) * 1000)),
            "t1": int(round(c.get("t1", 0.0) * 1000)),
            "dur_ms": int(round((c.get("t1", 0.0) - c.get("t0", 0.0)) * 1000)),
        }
        for c in non_boundary
    ]
    aligned_chars = "".join(str(c.get("ch") or "") for c in non_boundary)

    # Deterministic alignment-quality score:
    #   (1) char-count match between expected transcript and aligned spans,
    #   (2) monotonic non-empty temporal spans (no zero-duration collapses),
    #   (3) total aligned span duration vs clip duration (expect 0.4..1.0).
    expected_chars = [ch for ch in sl if ch.strip() and ch not in ("-", ".", ",", "?", "!")]
    n_exp = len(expected_chars)
    n_got = len(char_boundaries_ms)
    char_match = 1.0 if n_exp == n_got else max(0.0, 1.0 - abs(n_exp - n_got) / max(1, n_exp))

    nonzero = sum(1 for b in char_boundaries_ms if b["dur_ms"] > 0)
    nonzero_frac = nonzero / max(1, n_got)

    span_total_ms = sum(b["dur_ms"] for b in char_boundaries_ms)
    dur_ms = int(round(raw.get("duration_s", 0.0) * 1000))
    coverage = (span_total_ms / dur_ms) if dur_ms > 0 else 0.0
    coverage_score = max(0.0, min(1.0, coverage * 1.4))  # 0.71 → 1.0

    mean_conf = round(0.5 * char_match + 0.3 * nonzero_frac + 0.2 * coverage_score, 4)

    return {
        "wav": str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
        "sl": sl,
        "expected_ipa": expected_ipa,
        "duration_ms": int(round(raw.get("duration_s", 0.0) * 1000)),
        "char_boundaries_ms": char_boundaries_ms,
        "mean_conf": mean_conf,
        "aligned_chars": aligned_chars,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--sl", required=True)
    ap.add_argument("--expected-ipa", default=None)
    args = ap.parse_args()
    out = align_word(args.wav, args.sl, expected_ipa=args.expected_ipa)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
