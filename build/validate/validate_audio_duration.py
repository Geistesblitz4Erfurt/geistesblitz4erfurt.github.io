"""Audio-duration plausibility validator.

For each audio_asset with a known duration_ms, compare against expected:
    expected_ms = syllables * 180
    tolerance   = ±50%

Files outside that range are flagged (could be silence, wrong sample, multi-word phrase). Uses
``soundfile`` to probe duration if not already stored.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.ingest.schema import open_db, record_issue


def _probe_duration_ms(path: Path) -> int | None:
    try:
        import soundfile as sf
    except ImportError:
        return None
    try:
        info = sf.info(str(path))
        return int(info.duration * 1000)
    except Exception:
        return None


def run(db_path: Path) -> dict:
    conn = open_db(db_path)
    cur = conn.execute(
        """SELECT a.id, a.local_path, a.duration_ms, wf.surface, wf.syllables_json
           FROM audio_asset a JOIN word_form wf ON wf.id = a.word_form_id"""
    )
    report = {"checked": 0, "updated_durations": 0, "out_of_range": 0}
    for aid, local_path, dur_ms, surface, syll_json in cur.fetchall():
        report["checked"] += 1
        if dur_ms is None or dur_ms == 0:
            dur_ms = _probe_duration_ms(Path(local_path))
            if dur_ms:
                conn.execute("UPDATE audio_asset SET duration_ms = ? WHERE id = ?", (dur_ms, aid))
                report["updated_durations"] += 1
        if not dur_ms:
            continue
        n_syll = len(json.loads(syll_json)) if syll_json else max(1, len(surface) // 3)
        expected = n_syll * 180
        lo, hi = expected * 0.5, expected * 1.5
        if dur_ms < lo or dur_ms > hi:
            report["out_of_range"] += 1
            record_issue(
                conn, kind="audio_duration_off", severity="warn",
                entity_kind="audio", entity_id=str(aid),
                message=f"dur={dur_ms}ms expected≈{expected}ms n_syll={n_syll}",
                details={"path": local_path, "surface": surface},
            )
    conn.commit()
    conn.close()
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path("build/master.sqlite"))
    args = ap.parse_args()
    r = run(args.db)
    print(f"[validate_audio] {r}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
