"""Wrapper around ``clarinsi/slovene_g2p`` (Apache-2.0) for SL G2P cross-validation.

The upstream tool is a rule-based G2P implemented as the ``SloveneG2P`` class in
``sources/slovene_g2p/SloveneG2P.py``. Its main entry point is::

    convert_to_phonetic_transcription(accented_word, msd_sl, morphological_pattern_code)

It expects an **accented** orthographic form (e.g. ``slovénski`` not ``slovenski``)
because the accent diacritics carry the stress-and-length information the Sloleks
entry holds. That means we feed it Sloleks' ``accented_form`` column, the Sloleks
MSD tag, and the morphological pattern code — all readily available on each
``word_form`` row.

We cache a singleton converter (initialising it is slow — it reads half a dozen
TSV files and builds symbol tables) and expose a simple ``g2p(accented, msd, morph_code)``
function that returns an IPA string. The upstream code does a ``chdir`` to
``./resources`` implicitly via relative paths, so we wrap every call in a
``_with_cwd`` context manager that temporarily chdir's into the repo.

Cross-check usage::

    python -m build.g2p.wrapper --sample 1000

Reads 1000 random ``word_form`` rows from ``build/master.sqlite``, runs G2P on
``(accented_form, msd, morphology_pattern_code)``, and diffs the resulting IPA
against the Sloleks-stored IPA via Levenshtein distance. Prints a summary:
exact-match count, ≤1-edit count, and the top divergence patterns.

A ``quality_score`` side-effect is possible but disabled by default — the primary
purpose is cross-validation, not overwriting Sloleks.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import random
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
G2P_DIR = REPO_ROOT / "sources" / "slovene_g2p"
DB_PATH = REPO_ROOT / "build" / "master.sqlite"


@contextlib.contextmanager
def _with_cwd(path: Path):
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def _import_g2p_class():
    if str(G2P_DIR) not in sys.path:
        sys.path.insert(0, str(G2P_DIR))
    from SloveneG2P import SloveneG2P  # type: ignore  # noqa: E402
    return SloveneG2P


_CONVERTER = None


def _converter():
    """Singleton converter. IPA detailed representation, dictionary phoneme set."""
    global _CONVERTER
    if _CONVERTER is None:
        cls = _import_g2p_class()
        with _with_cwd(G2P_DIR):
            # representation_option: 'cjvt_ipa_detailed_representation' → IPA with
            # diacritics (stress mark + vowel length).
            # phoneme_set_option: 'cjvt_ipa_detailed_representation' (same) — the
            # upstream code uses this as a dict key to pick which phoneme column
            # to use from SloveneG2P_phoneme_set.json.
            # output_option: 'word' → return single IPA string per word.
            # Suppress the init-time schwa-rule chatter on stdout.
            import io
            buf = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = buf
            try:
                _CONVERTER = cls(
                    representation_option="cjvt_ipa_detailed_representation",
                    phoneme_set_option="cjvt_ipa_detailed_representation",
                    output_option="phoneme_string",
                )
            finally:
                sys.stdout = old_stdout
    return _CONVERTER


def g2p(accented_form: str, msd: str, morph_code: str = "") -> str | None:
    """Return CJVT-IPA transcription for an accented Sloleks surface form.

    Parameters
    ----------
    accented_form
        The ``accented_form`` column from ``word_form`` (e.g. ``slovénski``).
    msd
        Sloleks MSD tag (e.g. ``Agpmsny``).
    morph_code
        Morphological pattern code (Sloleks column). Empty string is safe for
        most forms; only matters when disambiguating schwa insertion.
    """
    if not accented_form or not accented_form.strip():
        return None
    conv = _converter()
    try:
        with _with_cwd(G2P_DIR):
            result = conv.convert_to_phonetic_transcription(
                accented_form.strip(), msd or "Unknown", morph_code or ""
            )
    except Exception:  # upstream raises bare exceptions on unsupported graphemes
        return None
    if not result:
        return None
    if isinstance(result, list):
        result = "".join(result)
    return str(result).strip() or None


def _normalize_ipa(s: str) -> str:
    """NFC-normalise and drop stress marks + length — we compare phoneme sequences only."""
    s = unicodedata.normalize("NFC", s)
    for ch in ("ˈ", "ˌ", "'", '"', "ː", ":"):
        s = s.replace(ch, "")
    return s.strip()


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


def cross_check_sample(n: int, seed: int = 42) -> dict:
    """Draw ``n`` random forms with IPA and compare G2P against Sloleks-IPA."""
    random.seed(seed)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Filter to rows that actually have IPA + accented_form + MSD
    cur.execute(
        "SELECT COUNT(*) FROM word_form WHERE ipa IS NOT NULL AND ipa != ''"
        " AND accented_form IS NOT NULL AND accented_form != ''"
    )
    total = cur.fetchone()[0]
    if total == 0:
        conn.close()
        raise SystemExit("no usable rows in word_form — check schema")
    # Randomly pick rowids. We use LIMIT ... OFFSET on random offsets.
    rowids = sorted(random.sample(range(1, total + 1), min(n * 4, total)))
    placeholders = ",".join("?" * len(rowids))
    cur.execute(
        f"SELECT accented_form, msd, ipa, morphology_pattern_code, surface "
        f"FROM word_form WHERE rowid IN ({placeholders}) LIMIT {n}",
        rowids,
    )
    rows = cur.fetchall()
    conn.close()

    exact = 0
    edit1 = 0
    empty = 0
    errors = 0
    divergence_patterns: Counter[tuple[str, str]] = Counter()
    samples: list[tuple[str, str, str, int]] = []

    for accented, msd, sloleks_ipa, morph_code, surface in rows:
        g2p_ipa = g2p(accented, msd, morph_code or "")
        if g2p_ipa is None:
            errors += 1
            continue
        a = _normalize_ipa(sloleks_ipa)
        b = _normalize_ipa(g2p_ipa)
        if not a or not b:
            empty += 1
            continue
        d = _levenshtein(a, b)
        if d == 0:
            exact += 1
        elif d == 1:
            edit1 += 1
        else:
            # collect top-10 worst
            divergence_patterns[(a, b)] += 1
        samples.append((surface, a, b, d))

    return {
        "n_requested": n,
        "n_processed": len(samples),
        "exact_match": exact,
        "edit_distance_1": edit1,
        "errors": errors,
        "empty": empty,
        "agreement_rate": (exact + edit1) / max(1, len(samples)),
        "worst_divergences": divergence_patterns.most_common(10),
        "first_20_samples": samples[:20],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="slovene_g2p cross-validator")
    ap.add_argument("--sample", type=int, default=0, help="run N-sample cross-check")
    ap.add_argument(
        "--words",
        default="",
        help=("Comma-separated accented forms for a smoke test: "
              "word[:msd[:morph_code]], e.g. 'slovénski:Agpmsny,Ljubljána:Npfsi'"),
    )
    args = ap.parse_args()

    if args.words:
        for tok in args.words.split(","):
            parts = tok.strip().split(":")
            w = parts[0].strip()
            m = parts[1].strip() if len(parts) > 1 else "Unknown"
            mc = parts[2].strip() if len(parts) > 2 else ""
            ipa = g2p(w, m, mc)
            print(f"{w}\t{m}\t{ipa or '<NONE>'}")
        return 0

    if args.sample:
        import json
        stats = cross_check_sample(args.sample)
        out = {
            "n_requested": stats["n_requested"],
            "n_processed": stats["n_processed"],
            "exact_match": stats["exact_match"],
            "edit_distance_1": stats["edit_distance_1"],
            "errors": stats["errors"],
            "empty": stats["empty"],
            "agreement_rate_within_1_edit": round(stats["agreement_rate"], 4),
            "worst_divergences_top10": [
                {"sloleks": a, "g2p": b, "count": c}
                for (a, b), c in stats["worst_divergences"]
            ],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        out_path = REPO_ROOT / "build" / "_g2p_crosscheck.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[g2p] wrote {out_path}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
