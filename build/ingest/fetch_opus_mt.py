"""Download Helsinki-NLP OPUS-MT models used for EN/DE ↔ SL bridge translation.

We pull four directional model snapshots via ``huggingface_hub.snapshot_download``
into ``sources/opus_mt/<pair>/``. Each model is roughly 300 MB.

Directions and fallbacks:

* ``en-sl``  : ``Helsinki-NLP/opus-mt-en-sl`` (direct)
* ``sl-en``  : ``Helsinki-NLP/opus-mt-sl-en`` (direct)
* ``de-sl``  : tries ``opus-mt-de-sl`` → ``opus-mt-de-sla`` (Slavic family).
               If neither exists, we mark it missing so ``build/translate/bridge.py``
               pivots via English.
* ``sl-de``  : tries ``opus-mt-sl-de`` → ``opus-mt-sla-de``. Same fallback rule.

License for all OPUS-MT checkpoints is **CC-BY-4.0** (per Tatoeba-MT terms).
We append one ``checksums.txt`` line per downloaded pair, recording the
resolved repo id and the local path.

Run::

    python -m build.ingest.fetch_opus_mt
    python -m build.ingest.fetch_opus_mt --pairs en-sl,sl-en
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OPUS_DIR = REPO_ROOT / "sources" / "opus_mt"
CHECKSUMS = REPO_ROOT / "sources" / "checksums.txt"

# (pair-name, [candidate hf repo ids in preference order])
# Direct en-sl / sl-en / de-sl / sl-de repos do not exist on HF (as of 2026-04).
# The only live Helsinki-NLP Slovenian bridges go through the Slavic multilingual
# checkpoint (*-sla / sla-*). Target language is selected at inference time via
# the ">>slv<<" prefix token (documented in the opus-mt-en-sla README).
# DE direction has no direct Helsinki model — bridge.py will pivot via EN.
PAIR_CANDIDATES: dict[str, list[str]] = {
    "en-sl": ["Helsinki-NLP/opus-mt-en-sla"],
    "sl-en": ["Helsinki-NLP/opus-mt-sla-en"],
    "de-sl": [],  # no direct model → bridge via EN
    "sl-de": [],  # no direct model → bridge via EN
}


def _snapshot(repo_id: str, local_dir: Path) -> bool:
    """Download a single HF repo snapshot. Returns False on 404/auth/net error."""
    try:
        from huggingface_hub import snapshot_download  # type: ignore
        from huggingface_hub.utils import (  # type: ignore
            HfHubHTTPError,
            RepositoryNotFoundError,
        )
    except ImportError as e:
        print(f"[fetch_opus_mt] missing dep huggingface_hub: {e}", file=sys.stderr)
        return False
    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_download(
            repo_id=repo_id,
            local_dir=str(local_dir),
            local_dir_use_symlinks=False,
            # only the inference-relevant files; skip flax / tf / rust weights
            allow_patterns=[
                "*.json",
                "*.txt",
                "*.model",
                "*.spm",
                "source.spm",
                "target.spm",
                "vocab.json",
                "tokenizer*",
                "pytorch_model.bin",
                "model.safetensors",
                "config.json",
                "generation_config.json",
                "special_tokens_map.json",
                "README.md",
                "LICENSE*",
            ],
        )
        return True
    except RepositoryNotFoundError:
        print(f"[fetch_opus_mt] repo not found: {repo_id}", file=sys.stderr)
        return False
    except HfHubHTTPError as e:
        print(f"[fetch_opus_mt] HTTP error for {repo_id}: {e}", file=sys.stderr)
        return False
    except Exception as e:  # pragma: no cover — defensive
        print(f"[fetch_opus_mt] unexpected error for {repo_id}: {e}", file=sys.stderr)
        return False


def _append_checksum(pair: str, repo_id: str, local_dir: Path) -> None:
    CHECKSUMS.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if CHECKSUMS.exists():
        existing = CHECKSUMS.read_text(encoding="utf-8")
    marker = f"opus_mt/{pair}"
    # idempotent: replace prior line for same pair if present
    kept = [ln for ln in existing.splitlines() if marker not in ln]
    kept.append(
        f"SNAPSHOT  sources/opus_mt/{pair}  "
        f"https://huggingface.co/{repo_id}  CC-BY-4.0"
    )
    CHECKSUMS.write_text("\n".join(kept) + "\n", encoding="utf-8")


def fetch_pair(pair: str) -> tuple[str | None, Path | None]:
    """Fetch one pair, trying candidates in order. Returns (resolved_repo_id, local_dir)."""
    if pair not in PAIR_CANDIDATES:
        raise ValueError(f"unknown pair: {pair}")
    local_dir = OPUS_DIR / pair
    for repo_id in PAIR_CANDIDATES[pair]:
        print(f"[fetch_opus_mt] {pair}: trying {repo_id}")
        if _snapshot(repo_id, local_dir):
            _append_checksum(pair, repo_id, local_dir)
            # leave a hint file so bridge.py knows which repo was resolved
            (local_dir / ".resolved_repo_id").write_text(repo_id, encoding="utf-8")
            print(f"[fetch_opus_mt] {pair}: ok → {local_dir}")
            return repo_id, local_dir
    print(f"[fetch_opus_mt] {pair}: NO candidate available — bridge will pivot via EN")
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pairs",
        default="en-sl,sl-en,de-sl,sl-de",
        help="Comma-separated subset of pairs to fetch",
    )
    args = ap.parse_args()
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    failures: list[str] = []
    for p in pairs:
        repo, _ = fetch_pair(p)
        if repo is None:
            failures.append(p)
    if failures:
        # de-sl / sl-de missing is expected and handled via EN pivot.
        for f in failures:
            if f not in ("de-sl", "sl-de"):
                print(f"[fetch_opus_mt] fatal: required pair {f} unavailable", file=sys.stderr)
                return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
