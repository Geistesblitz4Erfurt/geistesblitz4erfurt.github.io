"""Unit tests for build/validate/align/align_artur_samples.py.

No audio, no aligner, no DB — we feed the pure functions synthetic predicted +
observed tokens and confirm the metrics + JSON schema are right.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.validate.align.align_artur_samples import (
    ObservedPhone,
    ObservedToken,
    PredictedToken,
    SCHEMA_VERSION,
    aggregate,
    compute_token_result,
    synthesize_dry_run_results,
    tokenize,
    write_report,
)


# ---------------------------------------------------------------------------
# compute_token_result
# ---------------------------------------------------------------------------
def test_perfect_match_has_zero_distance_and_zero_delta():
    pred = PredictedToken(
        surface="hvala",
        ipa="xʋala",
        syllable_durations_ms=[180, 90],
        stress_syllable_idx=0,
    )
    obs = ObservedToken(
        surface="hvala",
        phones=[
            ObservedPhone("x", 0, 60),
            ObservedPhone("ʋ", 60, 100),
            ObservedPhone("a", 100, 280),   # 180 ms stressed syll [xʋa]
            ObservedPhone("l", 280, 340),
            ObservedPhone("a", 340, 400),   # 90 ms unstressed syll [la] (60+60≈120 approx)
        ],
    )
    r = compute_token_result(pred, obs)
    assert r.ipa_levenshtein == 0
    # stress position must match — the first partition should carry more duration
    assert r.stress_position_match is True
    assert r.predicted_stress_syllable_idx == 0


def test_ipa_substitution_counts_as_one_edit():
    pred = PredictedToken(
        surface="pes", ipa="pes", syllable_durations_ms=[120],
        stress_syllable_idx=0,
    )
    obs = ObservedToken(
        surface="pes",
        phones=[
            ObservedPhone("p", 0, 40),
            ObservedPhone("e", 40, 100),
            ObservedPhone("z", 100, 120),   # substitution s→z
        ],
    )
    r = compute_token_result(pred, obs)
    assert r.ipa_levenshtein == 1


def test_stress_duration_delta_is_absolute():
    pred = PredictedToken(
        surface="mama", ipa="mama", syllable_durations_ms=[200, 100],
        stress_syllable_idx=0,
    )
    obs = ObservedToken(
        surface="mama",
        phones=[
            ObservedPhone("m", 0, 30),
            ObservedPhone("a", 30, 180),   # stressed syll total ≈180 ms
            ObservedPhone("m", 180, 210),
            ObservedPhone("a", 210, 310),
        ],
    )
    r = compute_token_result(pred, obs)
    assert r.stress_duration_delta_ms == abs(200 - 180)


def test_mismatched_stress_position_flagged():
    # Predict stress on syllable 0, but observed has much longer syllable 1.
    pred = PredictedToken(
        surface="beseda", ipa="beseda", syllable_durations_ms=[80, 80, 80],
        stress_syllable_idx=0,
    )
    obs = ObservedToken(
        surface="beseda",
        phones=[
            ObservedPhone("b", 0, 20),
            ObservedPhone("e", 20, 60),
            ObservedPhone("s", 60, 80),
            ObservedPhone("e", 80, 300),   # unusually long — dominates syll 1
            ObservedPhone("d", 300, 320),
            ObservedPhone("a", 320, 360),
        ],
    )
    r = compute_token_result(pred, obs)
    assert r.stress_position_match is False
    assert r.observed_stress_syllable_idx != r.predicted_stress_syllable_idx


def test_empty_syllable_durations_does_not_crash():
    pred = PredictedToken(surface="x", ipa="x", syllable_durations_ms=[], stress_syllable_idx=0)
    obs = ObservedToken(surface="x", phones=[ObservedPhone("x", 0, 50)])
    r = compute_token_result(pred, obs)
    assert r.ipa_levenshtein == 0
    assert r.predicted_stress_duration_ms == 0


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------
def test_aggregate_empty_gives_zero_stats():
    agg = aggregate([])
    assert agg["n_tokens"] == 0
    assert agg["mean_ipa_levenshtein"] == 0.0
    assert agg["stress_agreement_rate"] == 0.0
    assert agg["schema_version"] == SCHEMA_VERSION
    assert agg["per_token"] == []


def test_aggregate_computes_means_medians_and_match_rate():
    results = synthesize_dry_run_results()
    agg = aggregate(results)
    assert agg["n_tokens"] == len(results)
    # means match direct computation
    assert agg["mean_ipa_levenshtein"] == pytest.approx(
        sum(r.ipa_levenshtein for r in results) / len(results)
    )
    # match rate is in [0, 1]
    assert 0.0 <= agg["stress_agreement_rate"] <= 1.0
    # per-token breakdown contains all tokens
    assert len(agg["per_token"]) == len(results)
    # every per-token entry has the required keys
    required = {
        "surface", "predicted_ipa", "observed_ipa", "ipa_levenshtein",
        "predicted_stress_duration_ms", "observed_stress_duration_ms",
        "stress_duration_delta_ms", "predicted_stress_syllable_idx",
        "observed_stress_syllable_idx", "stress_position_match",
    }
    for entry in agg["per_token"]:
        assert required.issubset(entry.keys())


# ---------------------------------------------------------------------------
# JSON emission / schema
# ---------------------------------------------------------------------------
def test_write_report_emits_valid_json_with_schema_version(tmp_path: Path):
    results = synthesize_dry_run_results()
    agg = aggregate(results)
    out = tmp_path / "nested" / "validation_alignment.json"
    write_report(agg, out)
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == SCHEMA_VERSION
    assert loaded["n_tokens"] == len(results)
    # top-level required keys
    for key in (
        "mean_ipa_levenshtein",
        "median_ipa_levenshtein",
        "mean_stress_duration_delta_ms",
        "median_stress_duration_delta_ms",
        "stress_agreement_rate",
        "per_token",
    ):
        assert key in loaded


def test_dry_run_results_are_deterministic():
    a = synthesize_dry_run_results()
    b = synthesize_dry_run_results()
    assert [r.surface for r in a] == [r.surface for r in b]
    assert [r.ipa_levenshtein for r in a] == [r.ipa_levenshtein for r in b]


# ---------------------------------------------------------------------------
# tokenize
# ---------------------------------------------------------------------------
def test_tokenize_strips_punctuation_and_lowercases():
    out = tokenize("Živjo, Slovenija! Kako si?")
    assert out == ["živjo", "slovenija", "kako", "si"]


def test_tokenize_preserves_hyphens_and_apostrophes():
    out = tokenize("čez-dan d'artagnan")
    assert out == ["čez-dan", "d'artagnan"]
