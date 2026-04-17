"""Extract prosodic-phrase-boundary patterns from UD_Slovenian-SST dependency parses.

UD-SST (Spoken Slovenian Treebank) annotates each sentence with UPOS, MSD, and dependency arcs
plus the source GOS/ARTUR audio URL. There is no explicit ToBI-style prosodic layer, but the
following *syntactic* cues correlate strongly with phrase-break positions in Slovene speech:

    1. Coordinating conjunctions (CCONJ, dep=cc)     -> minor break BEFORE token
    2. Subordinating conjunctions (SCONJ, dep=mark)  -> minor break BEFORE token
    3. Discourse markers / fillers (PART, INTJ)       -> minor break AROUND token
    4. Comma punctuation (PUNCT, dep=punct)          -> minor break
    5. Clitic chains (CCONJ+pron+verb adjacency)     -> NO break (one phrase)
    6. Appositions / dislocations (dep=parataxis)    -> major break BEFORE

We emit two artefacts:

    * ``build/_udsst_phrase_patterns.json``  — frequency tables of (upos, deprel, position)
      triples flanking known prosodic breaks, for later use in contour_model.py.
    * ``build/_udsst_gold_sentences.jsonl``  — one JSON per sentence with tokens +
      automatically-inferred break markers (score 0.0–1.0), used as gold for SLPROS-1 tests.

The score is a simple heuristic in [0, 1]:

    break(t, t+1) = 0.9  if punctuation at position t+1
                    0.7  if upos[t+1] in {CCONJ, SCONJ}
                    0.6  if deprel[t+1] in {parataxis, advcl, acl:relcl}
                    0.4  if upos[t] == INTJ or upos[t+1] == INTJ
                    0.0  otherwise

This matches the conservative rules in docs/PROSODY_RULES.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

UDSST_DIR = Path("sources/ud_sst")
OUT_PATTERNS = Path("build/_udsst_phrase_patterns.json")
OUT_GOLD = Path("build/_udsst_gold_sentences.jsonl")


def _parse_conllu(path: Path):
    """Yield sentences as list[dict{id,form,lemma,upos,xpos,feats,head,deprel}]."""
    sent: list[dict] = []
    meta: dict[str, str] = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            if sent:
                yield meta, sent
            sent = []
            meta = {}
            continue
        if ln.startswith("#"):
            if "=" in ln:
                k, _, v = ln[1:].partition("=")
                meta[k.strip()] = v.strip()
            continue
        cols = ln.split("\t")
        if len(cols) < 8 or "-" in cols[0] or "." in cols[0]:
            continue  # multiword tokens or empty nodes
        sent.append({
            "id": int(cols[0]),
            "form": cols[1],
            "lemma": cols[2],
            "upos": cols[3],
            "xpos": cols[4],
            "feats": cols[5],
            "head": cols[6],
            "deprel": cols[7],
        })
    if sent:
        yield meta, sent


def _break_score(cur: dict, nxt: dict) -> float:
    if nxt["upos"] == "PUNCT" and nxt["form"] in {",", ";", ":"}:
        return 0.9
    if nxt["upos"] == "PUNCT" and nxt["form"] in {".", "!", "?"}:
        return 1.0
    if nxt["upos"] in {"CCONJ", "SCONJ"}:
        return 0.7
    if nxt["deprel"] in {"parataxis", "advcl", "acl:relcl"}:
        return 0.6
    if cur["upos"] == "INTJ" or nxt["upos"] == "INTJ":
        return 0.4
    return 0.0


def process() -> None:
    patterns = Counter()
    OUT_PATTERNS.parent.mkdir(parents=True, exist_ok=True)
    out_gold = OUT_GOLD.open("w", encoding="utf-8")
    n_sent = 0
    for path in sorted(UDSST_DIR.glob("*.conllu")):
        for meta, sent in _parse_conllu(path):
            n_sent += 1
            breaks: list[dict] = []
            for i in range(len(sent) - 1):
                score = _break_score(sent[i], sent[i + 1])
                breaks.append({
                    "after_token_idx": i,
                    "score": round(score, 2),
                })
                if score > 0:
                    key = f"{sent[i]['upos']}→{sent[i+1]['upos']}/{sent[i+1]['deprel']}"
                    patterns[key] += 1
            record = {
                "sent_id": meta.get("sent_id"),
                "sound_url": meta.get("sound_url"),
                "speaker_id": meta.get("speaker_id"),
                "text": meta.get("text"),
                "tokens": [
                    {
                        "form": t["form"],
                        "lemma": t["lemma"],
                        "upos": t["upos"],
                        "xpos": t["xpos"],
                        "deprel": t["deprel"],
                    }
                    for t in sent
                ],
                "breaks": breaks,
            }
            out_gold.write(json.dumps(record, ensure_ascii=False) + "\n")
    out_gold.close()
    OUT_PATTERNS.write_text(
        json.dumps(
            {
                "n_sentences": n_sent,
                "patterns_top50": patterns.most_common(50),
                "total_break_occurrences": sum(patterns.values()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[udsst_phrase] processed {n_sent} sentences")
    print(f"[udsst_phrase] wrote {OUT_PATTERNS}")
    print(f"[udsst_phrase] wrote {OUT_GOLD}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.parse_args()
    process()
    return 0


if __name__ == "__main__":
    sys.exit(main())
