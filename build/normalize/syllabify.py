"""Rule-based syllabification for Slovenian IPA strings.

Principle: Maximum Onset. Given a sequence of IPA segments, split at positions where the
coda+onset division gives a legal Slovenian onset to the following syllable. A consonant cluster
between two vocalic nuclei is assigned to the onset of the following syllable if the cluster
itself (fully or partially) can begin a Slovenian word.

Syllabic r̩ counts as a nucleus. Length marks and stress marks are kept attached to their nucleus.
"""
from __future__ import annotations

import unicodedata

VOWELS = set("aeiouɛɔə")
LENGTH_MARK = "ː"
PRIMARY_STRESS = "ˈ"
SECONDARY_STRESS = "ˌ"
SYLLABIC_MARK = "\u0329"  # combining vertical line below → marks r̩, l̩, m̩, n̩
DIACRITIC_COMBINING = {"\u0301", "\u0311", "\u0300", "\u030F", "\u0303", "\u0302"}

# Attested word-initial onset clusters in Slovenian (enough for the MVP vocabulary; extensible).
LEGAL_ONSETS: set[tuple[str, ...]] = {
    ("b",), ("d",), ("f",), ("g",), ("ɡ",), ("h",), ("j",), ("k",), ("l",), ("ʎ",),
    ("m",), ("n",), ("ɲ",), ("p",), ("r",), ("s",), ("ʃ",), ("t",), ("v",), ("ʋ",),
    ("x",), ("z",), ("ʒ",),
    ("t͡s",), ("t͡ʃ",), ("d͡ʒ",),
    ("b", "r"), ("b", "l"), ("p", "r"), ("p", "l"), ("p", "ʎ"),
    ("d", "r"), ("t", "r"), ("k", "r"), ("k", "l"), ("k", "ʎ"),
    ("ɡ", "r"), ("ɡ", "l"), ("g", "r"), ("g", "l"),
    ("s", "l"), ("s", "m"), ("s", "n"), ("s", "p"), ("s", "t"), ("s", "k"), ("s", "v"),
    ("ʃ", "k"), ("ʃ", "p"), ("ʃ", "t"), ("ʃ", "l"), ("ʃ", "m"), ("ʃ", "n"),
    ("f", "r"), ("f", "l"), ("v", "r"), ("v", "l"), ("ʋ", "r"),
    ("z", "r"), ("z", "l"), ("z", "m"), ("z", "n"), ("z", "v"),
    ("ʒ", "v"), ("ʒ", "r"),
    ("s", "t", "r"), ("s", "t", "l"), ("s", "p", "r"), ("s", "p", "l"),
    ("s", "k", "r"), ("s", "k", "l"), ("s", "k", "v"),
    ("ʃ", "t", "r"), ("ʃ", "p", "r"), ("ʃ", "k", "r"),
    ("v", "p", "r"),  # vprašati
}


def tokenize_ipa(ipa: str) -> list[str]:
    """Split an IPA string into atomic segments preserving diacritics and length marks."""
    if not ipa:
        return []
    d = unicodedata.normalize("NFC", ipa)
    out: list[str] = []
    i = 0
    while i < len(d):
        ch = d[i]
        # skip stress marks as standalone tokens
        if ch in (PRIMARY_STRESS, SECONDARY_STRESS):
            out.append(ch)
            i += 1
            continue
        # two-char affricate ligatures
        two = d[i : i + 2]
        if two in ("t͡s", "t͡ʃ", "d͡ʒ"):
            out.append(two)
            i += 2
            continue
        # base char + optional combining diacritics + optional length mark
        seg = ch
        i += 1
        while i < len(d) and (d[i] in DIACRITIC_COMBINING or d[i] == SYLLABIC_MARK):
            seg += d[i]
            i += 1
        if i < len(d) and d[i] == LENGTH_MARK:
            seg += LENGTH_MARK
            i += 1
        out.append(seg)
    return out


def _is_nucleus(seg: str) -> bool:
    if not seg:
        return False
    base = unicodedata.normalize("NFD", seg)[0]
    if base in VOWELS:
        return True
    if SYLLABIC_MARK in seg:
        return True  # r̩, l̩
    return False


def syllabify(ipa: str) -> list[str]:
    """Return a list of syllable strings. Each syllable is a concatenated IPA substring.

    Stress and length marks remain on the syllable they belong to. Isolated stress marks at the
    start of a segment are attached to the following syllable's first consonant/vowel.
    """
    segs = tokenize_ipa(ipa)
    if not segs:
        return []

    # Locate nucleus positions.
    nuclei = [idx for idx, s in enumerate(segs) if _is_nucleus(s)]
    if not nuclei:
        return ["".join(segs)]

    # Walk through: for each consecutive pair of nuclei, decide the cluster split.
    syllables: list[str] = []
    cursor = 0  # inclusive start of current syllable in segs
    for k, nuc_idx in enumerate(nuclei):
        if k + 1 < len(nuclei):
            next_nuc = nuclei[k + 1]
            cluster = segs[nuc_idx + 1 : next_nuc]
            # Find the largest suffix of `cluster` that forms a legal onset.
            onset_len = 0
            for L in range(len(cluster), 0, -1):
                suffix = tuple(c for c in cluster[-L:] if c not in (PRIMARY_STRESS, SECONDARY_STRESS))
                if suffix in LEGAL_ONSETS:
                    onset_len = L
                    break
            # If no suffix is a legal onset, default: single-consonant onset if any
            if onset_len == 0 and cluster:
                onset_len = 1
            split_at = next_nuc - onset_len
            syllables.append("".join(segs[cursor:split_at]))
            cursor = split_at
        else:
            syllables.append("".join(segs[cursor:]))
            cursor = len(segs)
    return [s for s in syllables if s]


def count_syllables(ipa: str) -> int:
    return len(syllabify(ipa))
