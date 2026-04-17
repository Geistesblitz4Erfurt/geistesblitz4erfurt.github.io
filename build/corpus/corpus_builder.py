"""Expand template YAMLs into a flat sentence corpus.

Deterministic: sorted iteration over slot keys, stable cartesian product, capped by
variants_cap. Output: list of Sentence records ready for DB insertion.

Run standalone for inspection:
    python -m build.corpus.corpus_builder --templates build/corpus/templates --out /tmp/sentences.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

TEMPLATES_DIR = Path(__file__).parent / "templates"
SLOT_RE = re.compile(r"\{([A-Z_]+)\}")


@dataclass
class Sentence:
    id: str
    category: str
    register: str
    intonation: str
    sl: str
    en: str
    de: str | None = None
    source_template: str | None = None
    slot_values: dict[str, str] = field(default_factory=dict)


def _expand_template(
    template: str,
    slots: dict[str, list[str]],
    cap: int,
) -> list[tuple[str, dict[str, str]]]:
    """Stable cartesian expansion. Returns list of (filled_string, slot_values)."""
    if not slots:
        return [(template, {})]
    keys = sorted(slots.keys())
    value_lists = [slots[k] for k in keys]
    out: list[tuple[str, dict[str, str]]] = []
    for combo in itertools.product(*value_lists):
        filled = template
        values: dict[str, str] = {}
        for k, v in zip(keys, combo):
            filled = filled.replace(f"{{{k}}}", v)
            values[k] = v
        filled = re.sub(r"\s+", " ", filled).strip()
        filled = re.sub(r"\s+([,.?!])", r"\1", filled)
        out.append((filled, values))
        if len(out) >= cap:
            break
    return out


def _english_of(
    en_template: str | None,
    en_slots: dict[str, list[str]] | None,
    sl_slot_values: dict[str, str],
    sl_slots: dict[str, list[str]],
) -> str:
    """Project the same slot index in EN. Falls back to empty string when data missing."""
    if not en_template or not en_slots:
        return ""
    out = en_template
    sl_keys = sorted(sl_slots.keys())
    en_keys = sorted(en_slots.keys())
    if len(sl_keys) != len(en_keys):
        return en_template
    for sl_key, en_key in zip(sl_keys, en_keys):
        sl_values = sl_slots[sl_key]
        en_values = en_slots[en_key]
        sl_value = sl_slot_values.get(sl_key, "")
        try:
            idx = sl_values.index(sl_value)
            en_value = en_values[idx] if idx < len(en_values) else ""
        except ValueError:
            en_value = ""
        out = out.replace(f"{{{en_key}}}", en_value)
    out = re.sub(r"\s+", " ", out).strip()
    out = re.sub(r"\s+([,.?!])", r"\1", out)
    return out


def load_category(path: Path) -> list[Sentence]:
    with path.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)

    category = doc["category"]
    default_reg = doc.get("default_register", "formal")
    default_int = doc.get("default_intonation", "decl")

    sentences: list[Sentence] = []

    for fixed in doc.get("fixed") or []:
        sentences.append(
            Sentence(
                id=fixed["id"],
                category=category,
                register=fixed.get("register", default_reg),
                intonation=fixed.get("intonation", default_int),
                sl=fixed["sl"],
                en=fixed.get("en", ""),
                source_template=None,
            )
        )

    for tpl in doc.get("templates") or []:
        tpl_id = tpl["id"]
        template_str = tpl["template"]
        slots = tpl.get("slots") or {}
        cap = int(tpl.get("variants_cap", 6))
        en_template = tpl.get("en_template")
        en_slots = tpl.get("en_slots")
        intonation = tpl.get("intonation", default_int)
        register = tpl.get("register", default_reg)

        undeclared = set(SLOT_RE.findall(template_str)) - set(slots.keys())
        if undeclared:
            raise ValueError(
                f"Template {tpl_id}: slots {sorted(undeclared)} referenced but not declared"
            )

        expansions = _expand_template(template_str, slots, cap)
        for i, (sl_text, slot_values) in enumerate(expansions):
            en_text = _english_of(en_template, en_slots, slot_values, slots)
            sentences.append(
                Sentence(
                    id=f"{tpl_id}_{i:02d}",
                    category=category,
                    register=register,
                    intonation=intonation,
                    sl=sl_text,
                    en=en_text,
                    source_template=tpl_id,
                    slot_values=slot_values,
                )
            )

    return sentences


def build_corpus(templates_dir: Path = TEMPLATES_DIR) -> list[Sentence]:
    all_sentences: list[Sentence] = []
    for yaml_path in sorted(templates_dir.glob("*.yaml")):
        all_sentences.extend(load_category(yaml_path))

    seen: set[tuple[str, str]] = set()
    unique: list[Sentence] = []
    for s in all_sentences:
        key = (s.category, s.sl)
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)
    return unique


def extract_vocab(sentences: list[Sentence]) -> set[str]:
    """Return the set of distinct surface tokens used across all Slovenian sentences."""
    token_re = re.compile(r"\w+[\w'-]*", flags=re.UNICODE)
    vocab: set[str] = set()
    for s in sentences:
        for tok in token_re.findall(s.sl.lower()):
            vocab.add(tok)
    return vocab


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--templates", type=Path, default=TEMPLATES_DIR)
    ap.add_argument("--out", type=Path, default=Path("build/_corpus_preview.json"))
    ap.add_argument("--db", type=Path, default=None, help="Optional SQLite path to write into")
    args = ap.parse_args()

    sentences = build_corpus(args.templates)
    vocab = extract_vocab(sentences)

    payload = {
        "sentence_count": len(sentences),
        "unique_vocab_count": len(vocab),
        "by_category": {},
        "sentences": [asdict(s) for s in sentences],
        "vocab": sorted(vocab),
    }
    for s in sentences:
        payload["by_category"][s.category] = payload["by_category"].get(s.category, 0) + 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[corpus_builder] {len(sentences)} sentences, {len(vocab)} unique tokens")
    for cat, n in sorted(payload["by_category"].items()):
        print(f"  {cat}: {n}")
    print(f"[corpus_builder] preview written to {args.out}")

    if args.db:
        from build.ingest.schema import open_db, upsert_sentences

        conn = open_db(args.db)
        upsert_sentences(conn, sentences)
        conn.close()
        print(f"[corpus_builder] sentences written to {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
