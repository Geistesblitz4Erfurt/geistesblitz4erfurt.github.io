"""Generic text-to-SLPROS-1 synthesis pipeline.

Accepts arbitrary English *or* Slovenian input and returns a fully populated
SLPROS-1 envelope that a browser (or the build-time audio stitcher) can play.
The pipeline is deterministic, library-reusable, and identical to the one that
will eventually run behind the web frontend once the Marian model is ported to
ONNX — no training-time state, no stochastic components.

Steps
-----
1. If the input is English, translate to Slovenian via the local OPUS-MT
   ``en-sl`` checkpoint (``build.translate.bridge.bridge_en_to_sl``).
2. Tokenise the Slovenian string with the same ``TOKEN_RE`` the MVP uses.
3. Resolve every token's IPA via ``build.corpus.mvp_slpros1._resolve_ipa``:
   case-insensitive ``word_form`` hit, then lemma fallback, then grapheme
   fallback, then (opt-in) G2P. Resolution is memoised in process.
4. Apply the sandhi cascade (``build.prosody.sandhi.apply_sandhi``) — this is
   the step the offline MVP generator does **not** do yet, and it is what
   turns ``v Ljubljani`` into ``[u‿ʎuˈblaːni]``.
5. Hand the ``SentenceTokens`` bundle to ``build.prosody.contour_model.build_slpros1``
   with the CPT prior (default weight 0 — the UD-SST sweep picked pure rule).
6. Return a structured envelope:

       {
         "input": {"lang": "en", "text": "..."},
         "sl": "...",
         "tokens": [{"surface", "ipa", "upos", "role", "source", "sandhi_notes"}],
         "coverage": 0.95,
         "slpros1": {...},   # full SLPROS-1 schema
         "stats": {"n_tokens": 17, "n_resolved": 17, "n_sandhi_changes": 3},
       }

CLI::

    python -m build.pipeline.synthesize --en "Where is the train station?"
    python -m build.pipeline.synthesize --sl "Prosim za račun"
    python -m build.pipeline.synthesize --file prompts.txt --jsonl out.jsonl
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from build.corpus.mvp_slpros1 import (
    TOKEN_RE,
    _contour_type,
    _guess_upos,
    _resolve_ipa,
    _role_for,
)
from build.prosody.contour_model import build_slpros1
from build.prosody.cpt_prior import load_prior
from build.prosody.sandhi import SentenceTokens, Token, apply_sandhi

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "build" / "master.sqlite"


class Synthesizer:
    """Process-lifetime holder for DB cursor, CPT prior, and the MT bridge.

    Open once, call ``.synthesize(...)`` many times. The Marian model and
    tokenizer are imported lazily on the first EN call.
    """

    def __init__(self, db_path: Path = DB_PATH, *, register: str = "formal", cpt_weight: float = 0.0) -> None:
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA query_only = 1;")
        self.cur = self.conn.cursor()
        self.prior = load_prior()
        self.register = register
        self.cpt_weight = cpt_weight

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def _translate_en_to_sl(self, en: str) -> str:
        from build.translate.bridge import bridge_en_to_sl

        return bridge_en_to_sl(en)

    # ------------------------------------------------------------------
    # Core synthesis
    # ------------------------------------------------------------------

    def synthesize(
        self,
        text: str,
        *,
        lang: str = "sl",
        register: str | None = None,
    ) -> dict[str, Any]:
        if lang == "en":
            sl = self._translate_en_to_sl(text).strip()
            input_block = {"lang": "en", "text": text}
        elif lang == "sl":
            sl = text.strip()
            input_block = {"lang": "sl", "text": text}
        else:
            raise ValueError(f"unsupported input lang: {lang!r}")

        raw_tokens = TOKEN_RE.findall(sl)
        resolved: list[dict[str, Any]] = []
        toks: list[Token] = []
        for i, surf in enumerate(raw_tokens):
            upos = _guess_upos(surf, raw_tokens[i - 1] if i > 0 else None, is_first=(i == 0))
            ipa, src = _resolve_ipa(self.cur, surf, upos)
            role = _role_for(upos, surf)
            resolved.append({
                "surface": surf,
                "ipa": ipa,
                "upos": upos,
                "role": role,
                "source": src,
            })
            if ipa:
                toks.append(Token(
                    surface=surf,
                    ipa=ipa,
                    role=role,
                    upos=upos,
                    deprel=None,
                ))

        contour = _contour_type(sl)
        reg = register or self.register

        if not toks:
            return {
                "input": input_block,
                "sl": sl,
                "contour_type": contour,
                "tokens": resolved,
                "coverage": 0.0,
                "slpros1": None,
                "stats": {"n_tokens": len(resolved), "n_resolved": 0, "n_sandhi_changes": 0},
            }

        sent = SentenceTokens(tokens=toks, register=reg)
        apply_sandhi(sent)
        n_sandhi = sum(1 for t in sent.tokens if t.notes)

        # Push sandhi-notes back onto the resolved rows (matched by surface index order).
        sandhi_iter = iter(sent.tokens)
        for r in resolved:
            if not r["ipa"]:
                r["sandhi_notes"] = []
                continue
            st = next(sandhi_iter)
            r["ipa_after_sandhi"] = st.ipa
            r["role_after_sandhi"] = st.role
            r["sandhi_notes"] = list(st.notes)

        sp = build_slpros1(
            sent,
            contour_type=contour,
            cpt_prior=self.prior,
            cpt_weight=self.cpt_weight,
        )

        n_resolved = sum(1 for r in resolved if r["ipa"])
        coverage = n_resolved / len(resolved) if resolved else 0.0
        return {
            "input": input_block,
            "sl": sl,
            "contour_type": contour,
            "register": reg,
            "tokens": resolved,
            "coverage": round(coverage, 3),
            "slpros1": sp,
            "stats": {
                "n_tokens": len(resolved),
                "n_resolved": n_resolved,
                "n_sandhi_changes": n_sandhi,
            },
        }

    def close(self) -> None:
        self.conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render_human(rec: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"INPUT[{rec['input']['lang']}]  {rec['input']['text']}")
    if rec["input"]["lang"] == "en":
        lines.append(f"SL         {rec['sl']}")
    lines.append(
        f"contour={rec['contour_type']} coverage={rec['coverage']} "
        f"sandhi={rec['stats']['n_sandhi_changes']} tokens={rec['stats']['n_tokens']}"
    )
    for t in rec["tokens"]:
        ipa = t.get("ipa_after_sandhi") or t.get("ipa") or "-"
        notes = ",".join(t.get("sandhi_notes") or []) or "-"
        lines.append(f"  {t['surface']:<16} {t['upos']:<6} {t['role']:<8} /{ipa}/  [{t['source']}] {notes}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--en", action="append", default=[], help="English input (repeatable)")
    ap.add_argument("--sl", action="append", default=[], help="Slovenian input (skip translation; repeatable)")
    ap.add_argument("--file", type=Path, help="newline-delimited prompts (EN by default)")
    ap.add_argument("--lang", default="en", choices=["en", "sl"], help="language of --file prompts")
    ap.add_argument("--jsonl", type=Path, help="write JSONL output to this path")
    ap.add_argument("--json", action="store_true", help="print single record as JSON")
    ap.add_argument("--cpt-weight", type=float, default=0.0)
    ap.add_argument("--register", default="formal", choices=["formal", "informal"])
    args = ap.parse_args()

    syn = Synthesizer(cpt_weight=args.cpt_weight, register=args.register)

    records: list[dict[str, Any]] = []
    try:
        for txt in args.en:
            records.append(syn.synthesize(txt, lang="en"))
        for txt in args.sl:
            records.append(syn.synthesize(txt, lang="sl"))
        if args.file:
            for ln in args.file.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                records.append(syn.synthesize(ln, lang=args.lang))
    finally:
        syn.close()

    if not records:
        ap.error("provide at least one of --en / --sl / --file")

    if args.jsonl:
        with args.jsonl.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[synthesize] wrote {len(records)} records to {args.jsonl}")
    elif args.json:
        print(json.dumps(records[0] if len(records) == 1 else records, ensure_ascii=False, indent=2))
    else:
        for r in records:
            print(_render_human(r))
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
