"""Compare G2P-predicted IPA against MFA forced-alignment on ARTUR samples.

This is a SKELETON. It defines the flow and output schema so downstream work (hooking up
MFA, selecting a proper sample, etc.) can plug into a stable surface.

Inputs (expected once ARTUR is unpacked under sources/artur/):
    * A sentence-level transcription file (TRS/TextGrid/txt — TBD per ARTUR layout).
    * Accompanying audio clips (WAV/FLAC).

Pipeline:
    1. Load N sample sentences + their audio paths.
    2. Run build/normalize + future build/g2p on the orthographic sentence to get predicted
       phone sequence (IPA).
    3. Placeholder: load MFA forced-alignment output for the same audio (we'll wire MFA in
       a follow-up — see build/validate/align/).
    4. Emit one JSON blob per sample to build/_artur_sample.json with predicted/actual
       fields. The 'actual_*' fields are left empty pending MFA integration.

Run:
    PYTHONIOENCODING=utf-8 python -m build.validate.artur_alignment --sample 20
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

# Project G2P entry points — imported lazily so a missing module doesn't prevent
# running the skeleton for inventory purposes.
try:
    from build.normalize.ipa_normalizer import strip_brackets  # type: ignore
except Exception:  # pragma: no cover - skeleton tolerates partial pipeline
    strip_brackets = None  # type: ignore

ARTUR_SRC = Path("sources/artur")
SAMPLE_OUT = Path("build/_artur_sample.json")


@dataclass
class ArturSample:
    sample_id: str
    audio_path: str
    text: str
    predicted_ipa: str = ""
    predicted_phones: list[str] = field(default_factory=list)
    # Filled later from MFA TextGrid: list of {phone, start_s, end_s}
    actual_alignment: list[dict] = field(default_factory=list)
    # Filled later: phone-level precision/recall against predicted_phones
    comparison: dict = field(default_factory=dict)
    notes: str = ""


def iter_artur_samples(limit: int) -> Iterable[ArturSample]:
    """Yield skeleton samples. Real implementation walks sources/artur/ once unzipped.

    For now we only discover audio files shallowly so the skeleton runs even with the
    corpus absent. Text is left empty and marked for follow-up.
    """
    if not ARTUR_SRC.exists():
        return
    audio_exts = {".wav", ".flac", ".mp3", ".ogg"}
    count = 0
    for path in ARTUR_SRC.rglob("*"):
        if count >= limit:
            break
        if path.suffix.lower() not in audio_exts:
            continue
        yield ArturSample(
            sample_id=path.stem,
            audio_path=str(path).replace("\\", "/"),
            text="",  # TODO: load matching transcription once layout is confirmed
            notes="text+alignment pending; ARTUR layout not yet parsed",
        )
        count += 1


def run_g2p(text: str) -> tuple[str, list[str]]:
    """Placeholder G2P: returns ('', []) until build/g2p is wired.

    Once a canonical G2P function exists (e.g. build.g2p.predict), this wrapper should
    call it and hand back both a joined IPA string and a phone list.
    """
    if not text:
        return "", []
    # TODO: from build.g2p import predict_ipa; ipa = predict_ipa(text)
    ipa = ""
    if strip_brackets is not None:
        ipa = strip_brackets(ipa)
    phones: list[str] = []
    return ipa, phones


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=20, help="max samples to emit")
    ap.add_argument("--out", type=Path, default=SAMPLE_OUT)
    args = ap.parse_args()

    samples: list[ArturSample] = []
    for s in iter_artur_samples(args.sample):
        ipa, phones = run_g2p(s.text)
        s.predicted_ipa = ipa
        s.predicted_phones = phones
        samples.append(s)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "corpus": "ARTUR 1.0",
        "license": "CC-BY-4.0",
        "status": "skeleton",
        "n_samples": len(samples),
        "samples": [asdict(s) for s in samples],
    }
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[artur_alignment] wrote {args.out} ({len(samples)} samples)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
