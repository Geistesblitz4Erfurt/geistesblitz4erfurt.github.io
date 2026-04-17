"""Model Context Protocol server exposing SL-Pron as five tools.

Transport: stdio (Claude Desktop / Claude Agent SDK).

Tools
-----
  lookup_phrase       — O(1) phrasebook hit for an English phrase
  translate_and_speak — full EN → SL → SLPROS-1 + Web-Speech-directive
  validate_word       — deep L1–L6 word validator (writes verified_extensions
                        when score ≥ 0.90)
  list_categories     — category → record-count map of the shipped phrasebook
  get_phonetic        — IPA + syllables + stress index for a Slovenian word

Install & register::

    pip install mcp
    python -m mcp_server.sl_pron_mcp          # run standalone for smoke test
    # then in claude_desktop_config.json see mcp_server/manifest.json

Every tool response ends with a short ``next`` hint so agents can chain calls
deterministically (per the ⟶ NEXT convention in docs/AGENT_GUIDE.md).
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "api"
PHRASEBOOK_GZ = DATA_DIR / "phrasebook.json.gz"
VERIFIED_EXT = DATA_DIR / "verified_extensions.jsonl"
PENDING_AUDIT = DATA_DIR / "pending_audit.jsonl"
DB_PATH = ROOT / "build" / "master.sqlite"

from mcp.server.fastmcp import FastMCP  # type: ignore

mcp = FastMCP("sl-pron")

# --- lazy singletons ---------------------------------------------------------
_PB: dict | None = None
_SYN = None  # type: ignore


def _phrasebook() -> dict[str, dict]:
    global _PB
    if _PB is None:
        if PHRASEBOOK_GZ.exists():
            records = json.loads(gzip.open(PHRASEBOOK_GZ, "rb").read())
            _PB = {r["en_normalized"]: r for r in records}
        else:
            _PB = {}
    return _PB


def _synth():
    global _SYN
    if _SYN is None:
        from build.pipeline.synthesize import Synthesizer
        _SYN = Synthesizer()
    return _SYN


def _normalize_en(s: str) -> str:
    import re
    s = unicodedata.normalize("NFC", s).lower()
    s = re.sub(r"[^\w\s]+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _append_jsonl(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Tool: lookup_phrase
# ---------------------------------------------------------------------------
@mcp.tool()
def lookup_phrase(en: str) -> dict:
    """Return the O(1) phrasebook record for an English phrase, or null.

    Args:
        en: English phrase to look up (case/punctuation-insensitive).
    """
    key = _normalize_en(en)
    rec = _phrasebook().get(key)
    if rec is None:
        return {
            "found": False,
            "en_normalized": key,
            "next": "Call translate_and_speak(en=...) for the live pipeline.",
        }
    return {
        "found": True,
        "record": rec,
        "next": "Speak `record.sl` with voice `record.speech_directive` (lang=sl-SI, never fall back).",
    }


# ---------------------------------------------------------------------------
# Tool: translate_and_speak
# ---------------------------------------------------------------------------
@mcp.tool()
def translate_and_speak(en: str) -> dict:
    """Translate English → Slovenian and emit a Web-Speech directive.

    Args:
        en: Arbitrary English sentence.
    """
    key = _normalize_en(en)
    pb = _phrasebook()
    if key in pb:
        rec = dict(pb[key])
        return {"source": "phrasebook", "record": rec, "next": "Pass `record.speech_directive` to SpeechSynthesisUtterance."}

    syn = _synth()
    res = syn.synthesize(en, lang="en", register="formal")
    sl = res.get("sl", "")
    slpros1 = res.get("slpros1")
    from build.api.build_phrasebook import _derive_speech_directive
    directive = _derive_speech_directive(sl, slpros1)
    return {
        "source": "live",
        "record": {
            "en_text": en,
            "en_normalized": key,
            "sl": sl,
            "ipa_joined": " ".join(
                t.get("ipa_after_sandhi") or t.get("ipa") or "?"
                for t in res.get("tokens", [])
            ),
            "contour_type": res.get("contour_type"),
            "coverage": res.get("coverage", 0.0),
            "tokens": [
                {
                    "surface": t["surface"],
                    "ipa": t.get("ipa_after_sandhi") or t.get("ipa"),
                    "upos": t.get("upos"),
                    "source": t.get("source"),
                    "sandhi_notes": t.get("sandhi_notes") or [],
                }
                for t in res.get("tokens", [])
            ],
            "slpros1": slpros1,
            "speech_directive": directive,
        },
        "next": "Speak with lang=sl-SI; if no SL voice is installed, surface error "
                "(never_fall_back_to_other_language=true).",
    }


# ---------------------------------------------------------------------------
# Tool: validate_word
# ---------------------------------------------------------------------------
@mcp.tool()
def validate_word(en: str, sl: str, ipa: str = "") -> dict:
    """Deep L1–L6 validation of an EN↔SL word pair. Persists if score ≥ 0.90.

    Args:
        en: English gloss.
        sl: Slovenian surface form.
        ipa: Optional IPA hint (Sloleks preferred if available).
    """
    from build.g2p.wrapper import g2p as _g2p
    from build.translate.bridge import bridge_en_to_sl
    from build.validate.deep_validate import (
        MIN_LAYERS_PASS, VERIFIED_THRESHOLD, WORD_LAYER_WEIGHTS, _aggregate,
        word_layer_L1, word_layer_L2, word_layer_L3, word_layer_L4,
        word_layer_L5, word_layer_L6,
    )

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA query_only = 1;")
    cur = conn.cursor()
    cur.execute(
        "SELECT ipa, syllables_json FROM word_form WHERE LOWER(surface)=LOWER(?) "
        "AND ipa IS NOT NULL ORDER BY quality_score DESC, id ASC LIMIT 1",
        (sl,),
    )
    row = cur.fetchone()
    sloleks_ipa = row[0] if row else None
    syll = json.loads(row[1]) if (row and row[1]) else []

    rec = {
        "sl": sl,
        "en_gloss": en,
        "sloleks_ipa": sloleks_ipa or ipa,
        "syllables": syll,
        "syllable_count": len(syll),
        "audio_path": None,
    }
    layers = {
        "L1": word_layer_L1(rec),
        "L2": word_layer_L2(rec, cur, _g2p),
        "L3": word_layer_L3(rec),
        "L4": word_layer_L4(rec),
        "L5": {"pass": False, "conf": 0.0, "note": "no audio via MCP"},
        "L6": word_layer_L6(rec, bridge_en_to_sl),
    }
    conn.close()
    score, n_pass = _aggregate(layers, WORD_LAYER_WEIGHTS)
    verified = (score >= VERIFIED_THRESHOLD) and (n_pass >= MIN_LAYERS_PASS)
    now = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    out = {
        "ts": now,
        "en": en,
        "sl": sl,
        "ipa": sloleks_ipa or ipa,
        "score": score,
        "layers": layers,
        "verified": verified,
    }
    if verified:
        _append_jsonl(VERIFIED_EXT, {**out, "verifier": "mcp/validate_word", "pipeline_version": "SLPROS-1"})
        out["persisted"] = "verified_extensions"
    elif 0.70 <= score < VERIFIED_THRESHOLD:
        _append_jsonl(PENDING_AUDIT, {**out, "verifier": "mcp/validate_word"})
        out["persisted"] = "pending_audit"
    else:
        out["persisted"] = None
    out["next"] = (
        "Run rebuild_with_extensions to merge a verified record into the next phrasebook,"
        " or call translate_and_speak(en) to play it immediately."
    )
    return out


# ---------------------------------------------------------------------------
# Tool: list_categories
# ---------------------------------------------------------------------------
@mcp.tool()
def list_categories() -> dict:
    """Return category → count map for the shipped phrasebook."""
    pb = _phrasebook()
    cats: dict[str, int] = {}
    for r in pb.values():
        c = r.get("category", "uncategorized")
        cats[c] = cats.get(c, 0) + 1
    return {
        "total_records": len(pb),
        "category_count": len(cats),
        "categories": cats,
        "next": "Call translate_and_speak(en=<phrase>) to synthesize a specific record.",
    }


# ---------------------------------------------------------------------------
# Tool: get_phonetic
# ---------------------------------------------------------------------------
@mcp.tool()
def get_phonetic(sl: str) -> dict:
    """Return Sloleks IPA + syllables + stress index for a Slovenian word.

    Args:
        sl: Slovenian surface form.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA query_only = 1;")
    cur = conn.cursor()
    cur.execute(
        "SELECT ipa, syllables_json, stress_syllable_idx, accent_class "
        "FROM word_form WHERE LOWER(surface)=LOWER(?) AND ipa IS NOT NULL "
        "ORDER BY quality_score DESC, id ASC LIMIT 1",
        (sl,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"found": False, "sl": sl, "next": "Call validate_word(en, sl, ipa) to submit a new candidate."}
    ipa, syll_json, stress_idx, accent = row
    return {
        "found": True,
        "sl": sl,
        "ipa": ipa,
        "syllables": json.loads(syll_json) if syll_json else [],
        "stress_syllable_idx": stress_idx,
        "accent_class": accent,
        "next": "Render IPA alongside the orthographic form; pass `ipa` into your UI.",
    }


def main() -> int:
    # stdio transport so Claude Desktop can spawn & talk to us.
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
