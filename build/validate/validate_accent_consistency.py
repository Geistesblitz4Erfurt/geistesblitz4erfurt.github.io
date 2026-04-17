"""Stress-position consistency validator.

For each word_form row with IPA, re-compute the primary stress syllable index from the current IPA
and compare against the stored ``stress_syllable_idx``. Mismatches are logged. Also re-verifies the
``accent_class`` against ``detect_from_ipa``.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from build.ingest.schema import open_db, record_issue
from build.normalize.accent_decoder import detect_from_ipa, primary_stress_index


def run(db_path: Path) -> dict:
    conn = open_db(db_path)
    cur = conn.execute(
        "SELECT id, surface, ipa, accent_class, stress_syllable_idx FROM word_form "
        "WHERE ipa IS NOT NULL AND ipa != ''"
    )
    report = {"checked": 0, "stress_mismatch": 0, "accent_mismatch": 0}
    for row_id, surface, ipa, stored_class, stored_idx in cur.fetchall():
        report["checked"] += 1
        recomputed_class = detect_from_ipa(ipa)
        recomputed_idx = primary_stress_index(ipa)
        if stored_class and stored_class != "-" and recomputed_class != stored_class:
            report["accent_mismatch"] += 1
            record_issue(
                conn, kind="accent_class_mismatch", severity="warn",
                entity_kind="word_form", entity_id=surface,
                message=f"stored={stored_class} recomputed={recomputed_class}",
                details={"ipa": ipa},
            )
        if stored_idx >= 0 and recomputed_idx != stored_idx:
            report["stress_mismatch"] += 1
            record_issue(
                conn, kind="stress_idx_mismatch", severity="warn",
                entity_kind="word_form", entity_id=surface,
                message=f"stored={stored_idx} recomputed={recomputed_idx}",
                details={"ipa": ipa},
            )
    conn.commit()
    conn.close()
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path("build/master.sqlite"))
    args = ap.parse_args()
    r = run(args.db)
    print(f"[validate_accent] {r}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
