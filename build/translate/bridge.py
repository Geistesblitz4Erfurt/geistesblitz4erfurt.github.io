"""Bridge translation between EN/DE and SL using local OPUS-MT checkpoints.

Loads MarianMT models from ``sources/opus_mt/<pair>/`` (populated by
``build.ingest.fetch_opus_mt``) and exposes a small functional API::

    from build.translate.bridge import (
        bridge_en_to_sl, bridge_sl_to_en, bridge_de_to_sl, bridge_sl_to_de
    )

If the direct DE↔SL checkpoint is not present (the Helsinki-NLP hub no longer
publishes a standalone ``opus-mt-de-sl``), we transparently pivot through
English::

    de → en (opus-mt-de-en)   if present, or rely on de-sla fallback
    en → sl (opus-mt-en-sl)

The pivot keeps translation usable on build boxes that only have the two
direct EN↔SL models. Pivoting is best-effort; callers should not assume
pivot quality equals direct.

This module is **read-only at build time** — it does *not* touch
``build/master.sqlite``. Another process owns that file. Callers that want
to populate ``sentence.en_text`` / ``sentence.de_text`` must do so from the
outside.

CLI::

    python -m build.translate.bridge --sl "Dober dan" --target en
    python -m build.translate.bridge --smoke
"""
from __future__ import annotations

import argparse
import functools
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OPUS_DIR = REPO_ROOT / "sources" / "opus_mt"

# pair -> local directory inside sources/opus_mt/
_PAIR_DIRS = {
    "en-sl": OPUS_DIR / "en-sl",
    "sl-en": OPUS_DIR / "sl-en",
    "de-sl": OPUS_DIR / "de-sl",
    "sl-de": OPUS_DIR / "sl-de",
    # Pivot helpers (optional — only used if DE↔SL direct missing)
    "de-en": OPUS_DIR / "de-en",
    "en-de": OPUS_DIR / "en-de",
}

# The en-sl / sl-en / de-sl / sl-de folders actually hold Helsinki-NLP's
# ``opus-mt-en-sla`` / ``opus-mt-sla-en`` multilingual Slavic checkpoints.
# These models require an explicit target-language prefix token prepended to
# the source text to pick Slovenian out of {bos, hbs, hrv, srp, slv, ...}.
# Without ">>slv<<" the decoder falls back to the majority-language it saw
# most during training (Bosnian/Croatian), producing non-Slovene output.
_TARGET_PREFIX = {
    "en-sl": ">>slv<< ",
    "de-sl": ">>slv<< ",
}


def _pair_available(pair: str) -> bool:
    d = _PAIR_DIRS.get(pair)
    if d is None or not d.exists():
        return False
    # heuristic: MarianMT needs config.json + a weights file
    if not (d / "config.json").exists():
        return False
    if not ((d / "pytorch_model.bin").exists() or (d / "model.safetensors").exists()):
        return False
    return True


@functools.lru_cache(maxsize=8)
def _load(pair: str):
    """Lazy-load tokenizer + model for a direction pair. Cached per-process."""
    try:
        from transformers import MarianMTModel, MarianTokenizer  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "transformers not installed. Run: pip install transformers sentencepiece torch"
        ) from e
    d = _PAIR_DIRS[pair]
    if not d.exists():
        raise FileNotFoundError(
            f"OPUS-MT checkpoint missing: {d}. Run: python -m build.ingest.fetch_opus_mt --pairs {pair}"
        )
    tok = MarianTokenizer.from_pretrained(str(d))
    mdl = MarianMTModel.from_pretrained(str(d))
    mdl.eval()
    return tok, mdl


def _translate(pair: str, text: str) -> str:
    if not text or not text.strip():
        return ""
    try:
        import torch  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("torch not installed") from e
    tok, mdl = _load(pair)
    prefix = _TARGET_PREFIX.get(pair, "")
    batch = tok([prefix + text], return_tensors="pt", padding=True, truncation=True)
    with torch.no_grad():
        out = mdl.generate(
            **batch,
            max_length=256,
            num_beams=4,
            early_stopping=True,
        )
    return tok.batch_decode(out, skip_special_tokens=True)[0].strip()


def translate_batch(pair: str, texts: list[str], *, batch_size: int = 16, num_beams: int = 4) -> list[str]:
    """Batched variant — tokenises and generates in groups for throughput.

    Used by the broad validation harness to keep GPU inference saturated.
    """
    if not texts:
        return []
    try:
        import torch  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("torch not installed") from e
    tok, mdl = _load(pair)
    prefix = _TARGET_PREFIX.get(pair, "")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        mdl = mdl.to(device)
    out_all: list[str] = []
    for i in range(0, len(texts), batch_size):
        chunk = [prefix + t for t in texts[i : i + batch_size]]
        batch = tok(chunk, return_tensors="pt", padding=True, truncation=True)
        if device == "cuda":
            batch = {k: v.to(device) for k, v in batch.items()}
        with torch.no_grad():
            gen = mdl.generate(
                **batch,
                max_length=256,
                num_beams=num_beams,
                early_stopping=True,
            )
        out_all.extend(tok.batch_decode(gen, skip_special_tokens=True))
    return [s.strip() for s in out_all]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def bridge_en_to_sl(text: str) -> str:
    return _translate("en-sl", text)


def bridge_sl_to_en(text: str) -> str:
    return _translate("sl-en", text)


def bridge_de_to_sl(text: str) -> str:
    """DE → SL. Uses direct model if present, else pivots DE→EN→SL."""
    if _pair_available("de-sl"):
        return _translate("de-sl", text)
    if _pair_available("de-en"):
        en = _translate("de-en", text)
    else:
        raise FileNotFoundError(
            "No DE→SL path available. Fetch opus-mt-de-sl or opus-mt-de-en."
        )
    return _translate("en-sl", en)


def bridge_sl_to_de(text: str) -> str:
    """SL → DE. Uses direct model if present, else pivots SL→EN→DE."""
    if _pair_available("sl-de"):
        return _translate("sl-de", text)
    en = _translate("sl-en", text)
    if _pair_available("en-de"):
        return _translate("en-de", en)
    raise FileNotFoundError(
        "No SL→DE completion available. Fetch opus-mt-sl-de or opus-mt-en-de."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_DIRECTIONS = {
    ("en", "sl"): bridge_en_to_sl,
    ("sl", "en"): bridge_sl_to_en,
    ("de", "sl"): bridge_de_to_sl,
    ("sl", "de"): bridge_sl_to_de,
}

_SMOKE_PHRASES = [
    "Dober dan",
    "Hvala",
    "Koliko stane?",
    "Kje je postaja?",
    "Prosim za račun",
]


def _smoke() -> int:
    rc = 0
    for phrase in _SMOKE_PHRASES:
        for tgt in ("en", "de"):
            try:
                fn = _DIRECTIONS[("sl", tgt)]
                out = fn(phrase)
                print(f"[{tgt}] {phrase!r}\t→\t{out!r}")
            except Exception as e:
                print(f"[{tgt}] {phrase!r}\tERROR: {e}")
                rc = 1
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sl", help="Slovenian source text")
    ap.add_argument("--en", help="English source text")
    ap.add_argument("--de", help="German source text")
    ap.add_argument("--target", choices=["en", "de", "sl"], help="Target language")
    ap.add_argument("--smoke", action="store_true", help="Run canonical 5-phrase smoke test")
    args = ap.parse_args()

    if args.smoke:
        return _smoke()

    src_lang = None
    src_text = None
    for lang in ("sl", "en", "de"):
        val = getattr(args, lang)
        if val:
            src_lang = lang
            src_text = val
            break
    if not src_text or not args.target:
        ap.error("provide --sl/--en/--de and --target")

    key = (src_lang, args.target)
    if key not in _DIRECTIONS:
        ap.error(f"unsupported direction {src_lang}→{args.target}")
    print(_DIRECTIONS[key](src_text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
