"""Cross-source IPA agreement validator.

For every surface form with IPA from multiple sources (Sloleks, G2P, Wiktionary), compute pairwise
Levenshtein distance after normalization. Flag rows with distance > 1 into the ``validation_issue``
table and a summary JSON.

Run:

    python -m build.validate.validate_ipa_agreement --db build/master.sqlite
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from build.ingest.schema import open_db, record_issue
from build.normalize.ipa_normalizer import levenshtein, normalize


def _collect_ipa_by_surface(conn) -> dict[str, dict[str, str]]:
    cur = conn.execute(
        "SELECT surface, ipa, source_mask FROM word_form WHERE ipa IS NOT NULL AND ipa != ''"
    )
    grouped: dict[str, dict[str, str]] = defaultdict(dict)
    for surface, ipa, mask in cur.fetchall():
        ipa_n = normalize(ipa)
        for bit, name in ((1, "sloleks"), (2, "wiktionary"), (4, "g2p")):
            if mask & bit:
                grouped[surface].setdefault(name, ipa_n)
    return grouped


def run(db_path: Path, report_path: Path) -> dict:
    conn = open_db(db_path)
    grouped = _collect_ipa_by_surface(conn)
    report = {"checked": 0, "agreed": 0, "disagreed": 0, "disagreements": []}
    for surface, by_source in grouped.items():
        if len(by_source) < 2:
            continue
        report["checked"] += 1
        sources = list(by_source.items())
        worst = 0
        pair_note = None
        for i in range(len(sources)):
            for j in range(i + 1, len(sources)):
                d = levenshtein(sources[i][1], sources[j][1])
                if d > worst:
                    worst = d
                    pair_note = (sources[i], sources[j])
        if worst <= 1:
            report["agreed"] += 1
        else:
            report["disagreed"] += 1
            (sa, ia), (sb, ib) = pair_note
            report["disagreements"].append(
                {"surface": surface, "a_source": sa, "a_ipa": ia,
                 "b_source": sb, "b_ipa": ib, "distance": worst}
            )
            record_issue(
                conn,
                kind="ipa_disagreement",
                severity="warn",
                entity_kind="word_form",
                entity_id=surface,
                message=f"{sa}={ia} vs {sb}={ib} (d={worst})",
                details={"sources": dict(sources), "distance": worst},
            )
    conn.commit()
    conn.close()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path("build/master.sqlite"))
    ap.add_argument("--report", type=Path, default=Path("data/validation_report.json"))
    args = ap.parse_args()
    r = run(args.db, args.report)
    print(f"[validate_ipa] checked={r['checked']} agreed={r['agreed']} disagreed={r['disagreed']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
