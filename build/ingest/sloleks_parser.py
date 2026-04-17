"""Parse Sloleks 3.1 XML into the SQLite master DB.

Schema (from 00README.txt inside the ZIP):

  /lexicon/entry/head/headword/lemma
  /lexicon/entry/head/grammar/category                         (POS)
  /lexicon/entry/head/measureList/measure[@type='frequency']   (lemma freq)
  /lexicon/entry/body/wordFormList/wordForm
      /msd                                                     (MSD, JOS tagset)
      /formRepresentations/orthographyList/orthography/form    (surface)
      /formRepresentations/accentuationList[@type='dynamic']/accentuation/form   (accented form)
      /formRepresentations/pronunciationList/pronunciation/form[@script='IPA']
      /formRepresentations/pronunciationList/pronunciation/form[@script='SAMPA']

Two modes:

    --discover    Print tag/field summary from first 3000 entries
    (default)     Stream through ZIP and fill the master SQLite
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

from lxml import etree

from build.ingest.schema import SOURCE_SLOLEKS, open_db
from build.normalize.accent_decoder import (
    detect_from_ipa,
    detect_from_orthography,
    primary_stress_index,
)
from build.normalize.ipa_normalizer import normalize as norm_ipa
from build.normalize.syllabify import syllabify

DEFAULT_ZIP = Path("sources/sloleks_3.1.zip")
DEFAULT_DB = Path("build/master.sqlite")


def _txt(elem) -> str | None:
    if elem is None:
        return None
    t = (elem.text or "").strip()
    return t or None


def _iter_entries(zip_path: Path):
    """Yield (xml_filename, <entry> element) pairs, memory-safe."""
    with zipfile.ZipFile(zip_path) as zf:
        xml_names = sorted(n for n in zf.namelist() if n.endswith(".xml"))
        for name in xml_names:
            with zf.open(name) as fh:
                ctx = etree.iterparse(fh, events=("end",), tag="entry", huge_tree=True)
                for _, entry in ctx:
                    yield name, entry
                    entry.clear()
                    # free ancestors too
                    while entry.getprevious() is not None:
                        del entry.getparent()[0]


def _extract_entry(entry) -> dict | None:
    lemma = _txt(entry.find("head/headword/lemma"))
    if not lemma:
        return None
    pos = _txt(entry.find("head/grammar/category"))
    freq_el = entry.find("head/measureList/measure[@type='frequency']")
    lemma_freq = int(freq_el.text) if freq_el is not None and freq_el.text and freq_el.text.strip().isdigit() else None

    forms: list[dict] = []
    for wf in entry.findall("body/wordFormList/wordForm"):
        msd = _txt(wf.find("msd"))
        surface = _txt(wf.find("formRepresentations/orthographyList/orthography/form")) or lemma
        accented = _txt(
            wf.find("formRepresentations/accentuationList[@type='dynamic']/accentuation/form")
        )
        ipa = None
        sampa = None
        for p in wf.findall("formRepresentations/pronunciationList/pronunciation/form"):
            script = (p.get("script") or "").upper()
            txt = (p.text or "").strip()
            if not txt:
                continue
            if script == "IPA":
                ipa = txt
            elif script == "SAMPA":
                sampa = txt
        forms.append({
            "surface": surface,
            "msd": msd,
            "accented": accented,
            "ipa": ipa,
            "sampa": sampa,
        })
    return {"lemma": lemma, "pos": pos, "freq": lemma_freq, "forms": forms}


def discover(zip_path: Path, max_entries: int = 3000) -> None:
    fields = Counter()
    samples: dict[str, str] = {}
    n = 0
    for _fname, entry in _iter_entries(zip_path):
        rec = _extract_entry(entry)
        if not rec:
            continue
        n += 1
        for f in rec["forms"]:
            for key, val in f.items():
                if val:
                    fields[key] += 1
                    samples.setdefault(key, f"{rec['lemma']!r}: {val!r}")
        if rec["pos"]:
            fields["pos"] += 1
        if n >= max_entries:
            break
    print(f"[discover] scanned {n} entries, {sum(fields.values())} populated fields")
    for key, cnt in fields.most_common():
        print(f"  {cnt:6d}  {key:15s}  sample: {samples.get(key,'')}")


def parse_into_db(zip_path: Path, db_path: Path, limit: int | None = None) -> tuple[int, int]:
    conn = open_db(db_path)
    cur = conn.cursor()
    n_lemma = 0
    n_form = 0
    for _fname, entry in _iter_entries(zip_path):
        rec = _extract_entry(entry)
        if not rec:
            continue
        cur.execute(
            "INSERT OR IGNORE INTO lemma (lemma, pos, gos_freq) VALUES (?, ?, ?)",
            (rec["lemma"], rec["pos"], rec["freq"]),
        )
        cur.execute("SELECT id FROM lemma WHERE lemma = ?", (rec["lemma"],))
        lemma_id = cur.fetchone()[0]
        n_lemma += 1

        for f in rec["forms"]:
            ipa = norm_ipa(f["ipa"]) if f["ipa"] else None
            # Tone (R/F) is encoded in the orthographic accentuation diacritics,
            # NOT in Sloleks IPA (which has only stress ˈ + length ː). Prefer the
            # orthographic form for tone; fall back to IPA length-only heuristic.
            accent_cls = "-"
            stress_idx = -1
            if f["accented"]:
                accent_cls = detect_from_orthography(f["accented"])
            if ipa:
                stress_idx = primary_stress_index(ipa)
                if accent_cls == "-":
                    accent_cls = detect_from_ipa(ipa)
            syll_json = None
            if ipa:
                syll_json = json.dumps(syllabify(ipa), ensure_ascii=False)

            cur.execute(
                """INSERT OR REPLACE INTO word_form
                     (lemma_id, surface, msd, ipa, xsampa, accent_class,
                      syllables_json, stress_syllable_idx, quality_score, source_mask)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lemma_id,
                    f["surface"],
                    f["msd"],
                    ipa,
                    f["sampa"],
                    accent_cls,
                    syll_json,
                    stress_idx,
                    1.0 if ipa else 0.3,
                    SOURCE_SLOLEKS,
                ),
            )
            n_form += 1
            if limit and n_form >= limit:
                conn.commit()
                conn.close()
                return n_lemma, n_form
        if n_form % 10000 == 0:
            conn.commit()
            print(f"[parse] {n_lemma} lemmas, {n_form} forms")
    conn.commit()
    conn.close()
    return n_lemma, n_form


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    ap.add_argument("--out", type=Path, default=DEFAULT_DB)
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if not args.zip.exists():
        print(f"[sloleks_parser] ERROR: {args.zip} not found.", file=sys.stderr)
        return 1

    if args.discover:
        discover(args.zip)
        return 0

    nl, nf = parse_into_db(args.zip, args.out, limit=args.limit)
    print(f"[sloleks_parser] inserted {nl} lemmas, {nf} word forms → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
