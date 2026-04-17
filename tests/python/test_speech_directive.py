"""W3C-conformance unit tests for the speech_directive emitted per record.

Pulls ``data/api/phrasebook.json.gz`` if present; otherwise synthesises a
minimal record through ``_derive_speech_directive`` with a dummy slpros1.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from build.api.build_phrasebook import _derive_speech_directive

ROOT = Path(__file__).resolve().parents[2]
PHRASEBOOK = ROOT / "data" / "api" / "phrasebook.json.gz"


def _load_records() -> list[dict]:
    if PHRASEBOOK.exists():
        return json.loads(gzip.open(PHRASEBOOK, "rb").read())
    # fallback: single synthetic record
    slpros1 = {
        "version": "SLPROS-1",
        "tokens": [{"syllables": [{"dur_rel": 1.0}], "pause_after_ms": 0}],
        "final_pause_ms": 500,
    }
    return [
        {
            "id": "syn_test",
            "sl": "Dober dan.",
            "speech_directive": _derive_speech_directive("Dober dan.", slpros1),
        }
    ]


RECORDS = _load_records()


@pytest.mark.parametrize("rec", RECORDS)
def test_lang_is_sl_si(rec):
    assert rec["speech_directive"]["lang"] == "sl-SI"


@pytest.mark.parametrize("rec", RECORDS)
def test_utterance_ranges_within_w3c(rec):
    sd = rec["speech_directive"]
    assert 0.1 <= sd["rate"] <= 10.0
    assert 0.0 <= sd["pitch"] <= 2.0
    assert 0.0 <= sd["volume"] <= 1.0


@pytest.mark.parametrize("rec", RECORDS)
def test_fallback_locks_language(rec):
    fb = rec["speech_directive"]["fallback"]
    assert fb["never_fall_back_to_other_language"] is True
    assert fb["strategy"] == "concat_word_audio"


@pytest.mark.parametrize("rec", RECORDS)
def test_error_handling_covers_w3c_enum(rec):
    eh = rec["speech_directive"]["error_handling"]
    all_codes = set(eh["retry_fallback_on"] + eh["surface_to_user"] + eh["silent_ignore"])
    w3c = {
        "canceled", "interrupted", "audio-busy", "audio-hardware",
        "network", "synthesis-unavailable", "synthesis-failed",
        "language-unavailable", "voice-unavailable",
        "text-too-long", "invalid-argument", "not-allowed",
    }
    assert w3c.issubset(all_codes), f"missing: {w3c - all_codes}"


@pytest.mark.parametrize("rec", RECORDS)
def test_voice_preferences_non_empty(rec):
    prefs = rec["speech_directive"]["voice_preferences"]
    assert len(prefs) >= 3
    assert any("sl" in p.lower() or "lado" in p.lower() or "sloven" in p.lower() for p in prefs)


@pytest.mark.parametrize("rec", RECORDS)
def test_boundary_hint_w3c_values(rec):
    bh = rec["speech_directive"]["boundary_hint"]
    assert set(bh["expected_name_values"]) == {"word", "sentence"}


@pytest.mark.parametrize("rec", RECORDS)
def test_predicted_duration_below_chrome_limit(rec):
    d = rec["speech_directive"].get("total_predicted_duration_ms")
    if d is None:
        return
    assert d < rec["speech_directive"]["max_chunk_ms"], (
        f"record predicts {d}ms, > max_chunk_ms"
    )
