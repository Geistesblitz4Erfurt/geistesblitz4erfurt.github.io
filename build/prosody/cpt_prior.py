"""Read :file:`build/_prosody_cpt.json` as a Bayesian prior for SLPROS-1.

The CPT was trained from wav2vec2 forced-alignment over ~6100 UD-SST sentences.
Each bucket ``(upos, deprel, pos_bin)`` holds empirical mean+std of ``dur_rel``
and cents-offsets ``f0_start_ct`` / ``f0_end_ct`` (relative to each clip's own
10th-percentile F0 baseline).

Usage from the SLPROS-1 generator::

    prior = load_prior()
    hint = prior.lookup(upos="NOUN", deprel="root", pos_bin="initial")
    if hint and hint["dur_rel"]["n"] >= 20:
        dur_rel = hint["dur_rel"]["mean"]
    else:
        dur_rel = rule_based_fallback(...)

Fallback chain: (upos, deprel, pos_bin) → (upos marginal) → global. The
empirical prior is trusted only when ``n >= min_n`` (default 20) — below that
we stay with the deterministic rule tables in ``contour_model.py``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CPT_PATH = REPO_ROOT / "build" / "_prosody_cpt.json"


@dataclass(frozen=True)
class ProsodyPrior:
    """Empirical prior over (upos, deprel, pos_bin). Thin wrapper over the JSON."""

    buckets: dict
    by_upos: dict
    global_: dict
    meta: dict

    def lookup(
        self,
        upos: str,
        deprel: str | None = None,
        pos_bin: str = "medial",
        min_n: int = 20,
    ) -> dict | None:
        """Return the finest-grained bucket that meets ``min_n`` coverage."""
        keys = [
            f"{upos}|{deprel}|{pos_bin}" if deprel else None,
            # also try deprel-agnostic by scanning buckets that match upos+pos_bin
        ]
        for k in keys:
            if not k:
                continue
            entry = self.buckets.get(k)
            if entry and (entry.get("dur_rel", {}).get("n") or 0) >= min_n:
                return entry
        # marginal across upos
        marg = self.by_upos.get(upos)
        if marg and (marg.get("dur_rel", {}).get("n") or 0) >= min_n:
            return marg
        # global
        return self.global_

    def hz_offset_from_cents(self, cents: float, baseline_hz: float) -> float:
        return baseline_hz * (2 ** (cents / 1200.0))


def load_prior(path: Path = CPT_PATH) -> ProsodyPrior | None:
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return ProsodyPrior(
        buckets=d.get("by_upos_deprel_pos", {}),
        by_upos=d.get("by_upos", {}),
        global_=d.get("global", {}),
        meta=d.get("meta", {}),
    )


def _demo() -> int:
    p = load_prior()
    if p is None:
        print("no CPT found — run build.prosody.cpt_learner first")
        return 1
    for upos, deprel in [
        ("NOUN", "root"),
        ("ADP", "case"),
        ("CCONJ", "cc"),
        ("VERB", "root"),
        ("ADJ", "amod"),
        ("INTJ", "discourse:filler"),
    ]:
        for pos in ("initial", "medial", "final"):
            entry = p.lookup(upos, deprel, pos)
            if entry:
                d = entry.get("dur_rel", {})
                f0s = entry.get("f0_start_ct", {})
                f0e = entry.get("f0_end_ct", {})
                print(
                    f"{upos}|{deprel}|{pos}: "
                    f"n={d.get('n'):4} dur_rel={d.get('mean')} "
                    f"f0_start_ct={f0s.get('mean')} f0_end_ct={f0e.get('mean')}"
                )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_demo())
