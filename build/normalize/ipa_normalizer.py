"""Normalize IPA strings to a single canonical form for cross-source comparison.

Operations:
  * Unicode NFC normalization.
  * Replace common alternate forms with the canonical CJVT/Sloleks convention.
  * Strip or canonicalize whitespace, brackets.
  * Keep tonal diacritics attached to the correct vowel base character.
"""
from __future__ import annotations

import unicodedata

ALTERNATES = {
    "ɡ": "ɡ",          # U+0261 LATIN SMALL LETTER SCRIPT G, canonical phonetic g
    "g": "ɡ",          # ASCII g → phonetic g
    "ʧ": "t͡ʃ",
    "ʤ": "d͡ʒ",
    "ʦ": "t͡s",
    "ɑ": "a",          # Sloleks uses low front a
    "r̩": "r̩",          # make sure combining mark is canonical
    "'": "ˈ",          # ASCII apostrophe → primary stress mark if used as stress
}

BRACKET_CHARS = set("[]/")


def strip_brackets(ipa: str) -> str:
    return "".join(c for c in ipa if c not in BRACKET_CHARS).strip()


def normalize(ipa: str) -> str:
    """Return the canonical form of an IPA string.

    * NFC Unicode normalization (so diacritic + base is a single codepoint where possible).
    * Apostrophes used as stress markers converted to ˈ.
    * Alternate IPA characters mapped to CJVT convention.
    * Surrounding brackets (``/…/`` or ``[…]``) stripped.
    * Internal whitespace collapsed.
    """
    if not ipa:
        return ""
    s = unicodedata.normalize("NFC", ipa)
    s = strip_brackets(s)
    out: list[str] = []
    i = 0
    while i < len(s):
        # try 2-char replacement first (affricate ligatures)
        two = s[i : i + 2]
        if two in ALTERNATES:
            out.append(ALTERNATES[two])
            i += 2
            continue
        one = s[i]
        out.append(ALTERNATES.get(one, one))
        i += 1
    result = "".join(out)
    result = " ".join(result.split())
    return unicodedata.normalize("NFC", result)


def levenshtein(a: str, b: str) -> int:
    """Classic Levenshtein distance over full Unicode codepoints. O(len(a)*len(b))."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            )
        prev = curr
    return prev[-1]


def similarity(a: str, b: str) -> float:
    """Normalized similarity in [0, 1]. 1.0 = identical, 0.0 = completely different."""
    na = normalize(a)
    nb = normalize(b)
    if not na and not nb:
        return 1.0
    d = levenshtein(na, nb)
    return 1.0 - d / max(len(na), len(nb), 1)
