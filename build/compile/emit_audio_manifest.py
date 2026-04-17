"""Emit data/audio_manifest.json enumerating all redistributable audio assets.

Each entry: path (relative to /data), format, license, source, duration_ms, sha256, word_form.

Forvo entries are intentionally never written to audio_asset so they cannot leak here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.ingest.schema import open_db


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(db_path: Path, out_path: Path, data_root: Path) -> list[dict]:
    conn = open_db(db_path)
    rows = conn.execute(
        """SELECT a.id, a.local_path, a.format, a.source, a.license, a.duration_ms,
                  wf.surface
           FROM audio_asset a JOIN word_form wf ON wf.id = a.word_form_id"""
    ).fetchall()
    manifest: list[dict] = []
    for aid, lp, fmt, src, lic, dur, surface in rows:
        p = Path(lp)
        if not p.exists():
            continue
        rel = p.relative_to(data_root) if str(p).startswith(str(data_root)) else p
        manifest.append({
            "id": aid,
            "path": str(rel).replace("\\", "/"),
            "format": fmt,
            "source": src,
            "license": lic,
            "duration_ms": dur,
            "sha256": _sha256(p),
            "surface": surface,
        })
    conn.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path("build/master.sqlite"))
    ap.add_argument("--out", type=Path, default=Path("data/audio_manifest.json"))
    ap.add_argument("--root", type=Path, default=Path("data"))
    args = ap.parse_args()
    m = run(args.db, args.out, args.root)
    print(f"[audio_manifest] {len(m)} entries → {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
