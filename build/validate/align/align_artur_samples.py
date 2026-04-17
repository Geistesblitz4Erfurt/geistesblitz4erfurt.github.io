"""Alignment validator for SLPROS-1 prosody.

Compares our predicted Slovenian pronunciations (IPA + syllable durations +
stress position from ``build/master.sqlite``) against forced-aligned native
recordings (ARTUR, Common Voice SL, etc.).

For each (wav, transcript) input pair the script:

1. Tokenizes the reference transcript.
2. Looks up each token in ``build/master.sqlite`` and pulls:
   - ``ipa``               — predicted IPA
   - ``syllables_json``    — list of {nucleus, onset, coda, duration_ms}
   - ``stress_syllable_idx`` — which syllable bears primary stress
3. Runs forced alignment on the wav → observed per-phone intervals.
4. Computes per-token metrics:
   - ``ipa_levenshtein``     — phoneme-level edit distance predicted↔observed
   - ``stress_duration_delta_ms`` — |predicted − observed| on the stressed syllable
   - ``stress_position_match`` — boolean: did the observed longest/loudest
     syllable land on the predicted stress index?
5. Aggregates across the corpus and writes ``data/validation_alignment.json``
   with mean/median stats plus a per-token breakdown for the MVP vocabulary.

The script is importable (every heavy action is behind a function) and safe to
run without ARTUR data or the aligner installed: ``--dry-run`` synthesizes
alignment output so the JSON schema can be validated in CI.

Run:

    # smoke test (no audio, no aligner required)
    python build/validate/align/align_artur_samples.py --dry-run

    # real run (requires ctc-forced-aligner and populated DB)
    python build/validate/align/align_artur_samples.py \
        --samples sources/artur/aligned \
        --db build/master.sqlite \
        --out data/validation_alignment.json

See ``install_mfa.md`` for how to get the underlying aligner working.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# The validator only needs a Levenshtein function. Reuse the one from the
# existing IPA normalizer module so we stay consistent with the other
# validators in build/validate/.
try:
    from build.normalize.ipa_normalizer import levenshtein, normalize
except Exception:  # pragma: no cover - fallback for standalone runs
    def normalize(s: str) -> str:
        return unicodedata.normalize("NFC", s or "").strip()

    def levenshtein(a: str, b: str) -> int:
        if a == b:
            return 0
        if not a:
            return len(b)
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            curr = [i] + [0] * len(b)
            for j, cb in enumerate(b, 1):
                curr[j] = min(
                    prev[j] + 1,
                    curr[j - 1] + 1,
                    prev[j - 1] + (0 if ca == cb else 1),
                )
            prev = curr
        return prev[-1]


SCHEMA_VERSION = "1"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class PredictedToken:
    """What SLPROS-1 predicts for one surface token."""

    surface: str
    ipa: str
    syllable_durations_ms: list[int]
    stress_syllable_idx: int

    @property
    def stress_duration_ms(self) -> int:
        if not self.syllable_durations_ms:
            return 0
        idx = self.stress_syllable_idx
        if idx < 0 or idx >= len(self.syllable_durations_ms):
            return 0
        return self.syllable_durations_ms[idx]


@dataclass
class ObservedPhone:
    """One aligner-produced phone interval."""

    phone: str
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


@dataclass
class ObservedToken:
    """Aligner output restricted to one surface token."""

    surface: str
    phones: list[ObservedPhone] = field(default_factory=list)

    @property
    def observed_ipa(self) -> str:
        return "".join(p.phone for p in self.phones)

    @property
    def total_duration_ms(self) -> int:
        return sum(p.duration_ms for p in self.phones)


@dataclass
class TokenResult:
    surface: str
    predicted_ipa: str
    observed_ipa: str
    ipa_levenshtein: int
    predicted_stress_duration_ms: int
    observed_stress_duration_ms: int
    stress_duration_delta_ms: int
    predicted_stress_syllable_idx: int
    observed_stress_syllable_idx: int
    stress_position_match: bool


# ---------------------------------------------------------------------------
# Core metric computation  (all pure, no I/O — trivially unit-testable)
# ---------------------------------------------------------------------------
def _argmax(seq: list[int]) -> int:
    """Index of the max element; −1 for an empty sequence."""
    if not seq:
        return -1
    best_i, best_v = 0, seq[0]
    for i, v in enumerate(seq[1:], start=1):
        if v > best_v:
            best_i, best_v = i, v
    return best_i


def _partition_phones_into_syllables(
    phones: list[ObservedPhone], n_syllables: int
) -> list[list[ObservedPhone]]:
    """Naive greedy partition of observed phones into ``n_syllables`` buckets.

    We have no vowel/consonant classifier on the observed side (the aligner
    produces IPA-ish chars), so we approximate by grouping around vowel-like
    characters. If the counts don't match, we fall back to an even split over
    phone count.
    """
    if n_syllables <= 0 or not phones:
        return []

    # crude "is vowel" predicate for a phoneme string
    def _is_vowel(sym: str) -> bool:
        return any(c in "aeiouəɛɪɔʊɨʌæɒɜɑyø" for c in sym.lower())

    nuclei_idx = [i for i, p in enumerate(phones) if _is_vowel(p.phone)]
    if len(nuclei_idx) == n_syllables:
        buckets: list[list[ObservedPhone]] = [[] for _ in range(n_syllables)]
        # walk phones, assign to current bucket; advance bucket after a vowel
        bi = 0
        for i, p in enumerate(phones):
            buckets[bi].append(p)
            if bi < n_syllables - 1 and i == nuclei_idx[bi]:
                bi += 1
        return buckets

    # fallback: equal-size split
    sz = max(1, len(phones) // n_syllables)
    buckets = []
    for i in range(n_syllables):
        start = i * sz
        end = (i + 1) * sz if i < n_syllables - 1 else len(phones)
        buckets.append(phones[start:end])
    return buckets


def compute_token_result(pred: PredictedToken, obs: ObservedToken) -> TokenResult:
    """Pure function: derive all per-token metrics from predicted + observed."""
    predicted_ipa_n = normalize(pred.ipa)
    observed_ipa_n = normalize(obs.observed_ipa)
    dist = levenshtein(predicted_ipa_n, observed_ipa_n)

    buckets = _partition_phones_into_syllables(
        obs.phones, len(pred.syllable_durations_ms) or 1
    )
    obs_syll_durations = [sum(p.duration_ms for p in b) for b in buckets]
    obs_stress_idx = _argmax(obs_syll_durations)

    if 0 <= pred.stress_syllable_idx < len(obs_syll_durations):
        observed_stress_duration = obs_syll_durations[pred.stress_syllable_idx]
    else:
        observed_stress_duration = 0

    stress_delta = abs(pred.stress_duration_ms - observed_stress_duration)
    stress_match = obs_stress_idx == pred.stress_syllable_idx

    return TokenResult(
        surface=pred.surface,
        predicted_ipa=predicted_ipa_n,
        observed_ipa=observed_ipa_n,
        ipa_levenshtein=dist,
        predicted_stress_duration_ms=pred.stress_duration_ms,
        observed_stress_duration_ms=observed_stress_duration,
        stress_duration_delta_ms=stress_delta,
        predicted_stress_syllable_idx=pred.stress_syllable_idx,
        observed_stress_syllable_idx=obs_stress_idx,
        stress_position_match=stress_match,
    )


def aggregate(results: list[TokenResult]) -> dict[str, Any]:
    """Mean/median stats across all per-token results."""
    n = len(results)
    agg: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "n_tokens": n,
        "mean_ipa_levenshtein": 0.0,
        "median_ipa_levenshtein": 0.0,
        "mean_stress_duration_delta_ms": 0.0,
        "median_stress_duration_delta_ms": 0.0,
        "stress_agreement_rate": 0.0,
        "per_token": [asdict(r) for r in results],
    }
    if n == 0:
        return agg
    dists = [r.ipa_levenshtein for r in results]
    deltas = [r.stress_duration_delta_ms for r in results]
    matches = sum(1 for r in results if r.stress_position_match)
    agg.update(
        mean_ipa_levenshtein=statistics.fmean(dists),
        median_ipa_levenshtein=statistics.median(dists),
        mean_stress_duration_delta_ms=statistics.fmean(deltas),
        median_stress_duration_delta_ms=statistics.median(deltas),
        stress_agreement_rate=matches / n,
    )
    return agg


def write_report(agg: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Prediction lookup (SQLite)
# ---------------------------------------------------------------------------
def load_predicted_token(
    conn: sqlite3.Connection, surface: str
) -> PredictedToken | None:
    """Read ipa + syllable data for a surface form.

    Returns ``None`` when the surface is not in the DB. Callers skip such
    tokens rather than fail — the validator is best-effort over whatever
    vocabulary is available.
    """
    row = conn.execute(
        "SELECT ipa, syllables_json, stress_syllable_idx "
        "FROM word_form WHERE surface = ? LIMIT 1",
        (surface,),
    ).fetchone()
    if not row:
        return None
    ipa, syll_json, stress_idx = row
    durations: list[int] = []
    if syll_json:
        try:
            sylls = json.loads(syll_json)
            for s in sylls:
                d = s.get("duration_ms") if isinstance(s, dict) else None
                durations.append(int(d) if d is not None else 0)
        except (json.JSONDecodeError, TypeError, ValueError):
            durations = []
    return PredictedToken(
        surface=surface,
        ipa=ipa or "",
        syllable_durations_ms=durations,
        stress_syllable_idx=int(stress_idx) if stress_idx is not None else 0,
    )


# ---------------------------------------------------------------------------
# Forced-alignment backends
# ---------------------------------------------------------------------------
def _align_with_ctc(wav_path: Path, transcript: str) -> list[ObservedToken]:
    """Align with ctc-forced-aligner (pip-installable, Windows-friendly).

    Imports are local so the module remains importable without the package.
    """
    from ctc_forced_aligner import (  # type: ignore
        generate_emissions,
        get_alignments,
        get_spans,
        load_alignment_model,
        load_audio,
        postprocess_results,
        preprocess_text,
    )

    model, tokenizer = load_alignment_model(device="cpu")
    audio = load_audio(str(wav_path), model.dtype, model.device)
    emissions, stride = generate_emissions(model, audio, batch_size=1)
    tokens_star, text_star = preprocess_text(transcript, language="slv")
    segments, scores, blank_id = get_alignments(emissions, tokens_star, tokenizer)
    spans = get_spans(tokens_star, segments, blank_id)
    word_timestamps = postprocess_results(text_star, spans, stride, scores)

    observed: list[ObservedToken] = []
    for w in word_timestamps:
        surface = w.get("text", "")
        start_ms = int(float(w.get("start", 0.0)) * 1000)
        end_ms = int(float(w.get("end", 0.0)) * 1000)
        # The CTC aligner is word-level out of the box; approximate per-phone
        # by spreading the word interval evenly across its characters.
        chars = [c for c in surface if not c.isspace()]
        if not chars:
            continue
        step = (end_ms - start_ms) / max(1, len(chars))
        phones = [
            ObservedPhone(
                phone=ch,
                start_ms=int(start_ms + i * step),
                end_ms=int(start_ms + (i + 1) * step),
            )
            for i, ch in enumerate(chars)
        ]
        observed.append(ObservedToken(surface=surface, phones=phones))
    return observed


def _align_with_mfa(
    wav_path: Path, transcript: str, acoustic: str, dictionary: str
) -> list[ObservedToken]:
    """Align with Montreal Forced Aligner. Requires conda install (see install_mfa.md)."""
    # MFA integration is a subprocess shell-out because it lives in its own
    # conda env. This is a stub that documents the contract; wire it up once
    # MFA is installed.
    raise NotImplementedError(
        "MFA backend not wired up yet — install per build/validate/align/install_mfa.md "
        "then implement subprocess call to `mfa align`."
    )


# ---------------------------------------------------------------------------
# Sample I/O
# ---------------------------------------------------------------------------
def discover_samples(samples_dir: Path) -> list[tuple[Path, str]]:
    """Find (wav, transcript) pairs. Each wav must have a sibling .txt or .lab."""
    pairs: list[tuple[Path, str]] = []
    for wav in sorted(samples_dir.glob("*.wav")):
        for ext in (".txt", ".lab"):
            tx = wav.with_suffix(ext)
            if tx.exists():
                pairs.append((wav, tx.read_text(encoding="utf-8").strip()))
                break
    return pairs


def tokenize(transcript: str) -> list[str]:
    """Whitespace-split + strip punctuation, preserving Slovenian characters."""
    out: list[str] = []
    for raw in transcript.split():
        clean = "".join(
            ch for ch in raw if ch.isalpha() or ch == "-" or ch == "'"
        ).lower()
        if clean:
            out.append(clean)
    return out


# ---------------------------------------------------------------------------
# Dry-run synthesis
# ---------------------------------------------------------------------------
def synthesize_dry_run_results() -> list[TokenResult]:
    """Return a tiny deterministic result set to exercise the JSON schema."""
    synthetic = [
        (
            PredictedToken(
                surface="slovenija",
                ipa="ˈsloveːnija",
                syllable_durations_ms=[90, 180, 90, 90],
                stress_syllable_idx=1,
            ),
            ObservedToken(
                surface="slovenija",
                phones=[
                    ObservedPhone("s", 0, 50),
                    ObservedPhone("l", 50, 90),
                    ObservedPhone("o", 90, 150),
                    ObservedPhone("v", 150, 200),
                    ObservedPhone("e", 200, 370),
                    ObservedPhone("n", 370, 420),
                    ObservedPhone("i", 420, 490),
                    ObservedPhone("j", 490, 530),
                    ObservedPhone("a", 530, 610),
                ],
            ),
        ),
        (
            PredictedToken(
                surface="hvala",
                ipa="ˈxʋaːla",
                syllable_durations_ms=[180, 90],
                stress_syllable_idx=0,
            ),
            ObservedToken(
                surface="hvala",
                phones=[
                    ObservedPhone("x", 0, 60),
                    ObservedPhone("v", 60, 100),
                    ObservedPhone("a", 100, 260),
                    ObservedPhone("l", 260, 320),
                    ObservedPhone("a", 320, 400),
                ],
            ),
        ),
    ]
    return [compute_token_result(p, o) for p, o in synthetic]


# ---------------------------------------------------------------------------
# End-to-end driver
# ---------------------------------------------------------------------------
def run(
    samples_dir: Path | None,
    db_path: Path,
    out_path: Path,
    aligner: str,
    mfa_acoustic: str | None = None,
    mfa_dict: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if dry_run:
        results = synthesize_dry_run_results()
        agg = aggregate(results)
        agg["mode"] = "dry_run"
        write_report(agg, out_path)
        return agg

    if not samples_dir or not samples_dir.exists():
        raise FileNotFoundError(
            f"samples dir not found: {samples_dir}. "
            "Use --dry-run if no ARTUR clips are available yet."
        )
    if not db_path.exists():
        raise FileNotFoundError(
            f"DB not found: {db_path}. The build/master.sqlite is populated by "
            "the ingest/compile pipeline."
        )

    conn = sqlite3.connect(db_path)
    try:
        results: list[TokenResult] = []
        for wav, transcript in discover_samples(samples_dir):
            if aligner == "ctc":
                observed_tokens = _align_with_ctc(wav, transcript)
            elif aligner == "mfa":
                observed_tokens = _align_with_mfa(
                    wav, transcript, mfa_acoustic or "", mfa_dict or ""
                )
            else:
                raise ValueError(f"unknown aligner: {aligner}")

            obs_by_surface = {normalize(t.surface).lower(): t for t in observed_tokens}
            for surface in tokenize(transcript):
                pred = load_predicted_token(conn, surface)
                if pred is None:
                    continue
                obs = obs_by_surface.get(surface)
                if obs is None:
                    continue
                results.append(compute_token_result(pred, obs))
    finally:
        conn.close()

    agg = aggregate(results)
    agg["mode"] = "live"
    write_report(agg, out_path)
    return agg


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", type=Path, default=None,
                    help="Directory of .wav + .txt reference pairs.")
    ap.add_argument("--db", type=Path, default=Path("build/master.sqlite"))
    ap.add_argument("--out", type=Path,
                    default=Path("data/validation_alignment.json"))
    ap.add_argument("--aligner", choices=("ctc", "mfa"), default="ctc")
    ap.add_argument("--mfa-acoustic", default="slovenian_mfa")
    ap.add_argument("--mfa-dict", default="slovenian_mfa")
    ap.add_argument("--dry-run", action="store_true",
                    help="Skip audio + DB; synthesize fake alignment output "
                         "and emit the JSON schema for CI checks.")
    args = ap.parse_args(argv)

    agg = run(
        samples_dir=args.samples,
        db_path=args.db,
        out_path=args.out,
        aligner=args.aligner,
        mfa_acoustic=args.mfa_acoustic,
        mfa_dict=args.mfa_dict,
        dry_run=args.dry_run,
    )
    mode = agg.get("mode", "?")
    print(
        f"[align_validator mode={mode}] n={agg['n_tokens']} "
        f"mean_lev={agg['mean_ipa_levenshtein']:.2f} "
        f"mean_dur_delta_ms={agg['mean_stress_duration_delta_ms']:.1f} "
        f"stress_match={agg['stress_agreement_rate']:.0%}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
