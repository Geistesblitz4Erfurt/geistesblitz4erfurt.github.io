"""Aggregate every evidence artefact into a single dashboard JSON.

Reads (all optional except phrasebook):

  data/api/phrasebook.json.gz
  data/api/proof_report.json                (G1–G10 corpus proof)
  data/api/deep_validation_report.json      (L1–L6 / S1–S5)
  data/api/verified_words.json              (Score ≥ 0.90 only)
  data/api/audit_log.jsonl                  (server-side audits)
  data/api/verified_extensions.jsonl        (loop-grown records)
  data/api/pending_audit.jsonl              (awaiting human verdict)

Writes:

  data/api/evidence_dashboard.json

Schema (stable v1)::

    {
      "schema": "evidence_dashboard.v1",
      "generated_at": "…Z",
      "pipeline_version": "SLPROS-1",
      "shipped": { ... counts / sha1 / sizes ... },
      "proofs": {
        "corpus_G1_G10": {...},
        "deep_words":    {...},
        "deep_sentences":{...}
      },
      "loop": { "verified_extensions": N, "pending_audit": N, "audit_submissions": N },
      "verdicts": { verdict_string -> count }
    }

Run::

    python -m build.validate.evidence_dashboard
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "data" / "api"
OUT = API / "evidence_dashboard.json"


def _sha1(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _verdicts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    counts: dict[str, int] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            v = rec.get("verdict", "unknown")
            counts[v] = counts.get(v, 0) + 1
    return counts


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def build() -> dict:
    pb_gz = API / "phrasebook.json.gz"
    pb_records = []
    if pb_gz.exists():
        pb_records = json.loads(gzip.open(pb_gz, "rb").read())

    proof = _load_json(API / "proof_report.json") or {}
    deep = _load_json(API / "deep_validation_report.json") or {}
    verified = _load_json(API / "verified_words.json") or {"count": 0}

    categories: dict[str, int] = {}
    for r in pb_records:
        categories[r.get("category", "uncategorized")] = categories.get(r.get("category", "uncategorized"), 0) + 1

    return {
        "schema": "evidence_dashboard.v1",
        "generated_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "pipeline_version": "SLPROS-1",
        "shipped": {
            "record_count": len(pb_records),
            "category_count": len(categories),
            "categories": categories,
            "phrasebook_gz_sha1": _sha1(pb_gz),
            "phrasebook_gz_size": pb_gz.stat().st_size if pb_gz.exists() else 0,
        },
        "proofs": {
            "corpus_G1_G10": {
                "all_passed": bool(proof.get("all_passed")) if "all_passed" in proof else None,
                "guarantees": proof.get("guarantees") or proof.get("checks"),
                "back_translation": proof.get("back_translation_proof") or proof.get("back_translation"),
            },
            "deep_words": deep.get("word_aggregate"),
            "deep_sentences": deep.get("sentence_aggregate"),
            "verified_gold_words": verified.get("count"),
        },
        "loop": {
            "verified_extensions": _jsonl_count(API / "verified_extensions.jsonl"),
            "pending_audit": _jsonl_count(API / "pending_audit.jsonl"),
            "audit_submissions": _jsonl_count(API / "audit_log.jsonl"),
        },
        "verdicts": _verdicts(API / "audit_log.jsonl"),
    }


def main() -> int:
    dash = build()
    OUT.write_text(json.dumps(dash, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dash, ensure_ascii=False, indent=2))
    print(f"[dashboard] wrote {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
