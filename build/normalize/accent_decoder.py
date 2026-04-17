"""Decode Slovenian accent diacritics from Sloleks dynamic accentuation → SLPROS-1 accent_class.

**Scientific note on scope.** Sloleks 3.1 only provides *dynamic* accentuation (stress position +
length of the stressed syllable). It does **not** include a tonemic layer, so rising/falling tone
cannot be inferred from Sloleks alone. We therefore emit the following class inventory:

    RL  long rising   ┐ require an external tonemic source
    FL  long falling  │  (SSKJ-T, Forvo spot-check, or GOS F0 analysis)
    RS  short rising  │
    FS  short falling ┘
    L   long stressed, tone unknown (from Sloleks dynamic accentuation)
    S   short stressed, tone unknown
    -   unstressed / no accentuation info

Dynamic accentuation diacritics observed in Sloleks 3.1 (from the actual ZIP, 2026-04):

    U+0301  ´   combining acute         → L (stressed long)
    U+0300  `   combining grave         → S (stressed short)
    U+0302  ̂   combining circumflex    → L (stressed long — variant)
    U+030C  ̌   combining caron         → S (stressed short — variant)

The corresponding IPA layer encodes length via ``ː`` and stress via ``ˈ``.

When a downstream module binds in tonemic data (from SSKJ-T or Forvo), it can upgrade L→RL/FL and
S→RS/FS. Until then we refuse to fabricate tone.
"""
from __future__ import annotations

import unicodedata

# Combining diacritics observed in Sloleks 3.1 dynamic accentuation.
COMBINING_ACUTE = "\u0301"          # long stressed
COMBINING_GRAVE = "\u0300"          # short stressed
COMBINING_CIRCUMFLEX = "\u0302"     # long stressed (variant, legacy)
COMBINING_CARON = "\u030C"          # short stressed (variant, legacy)

# Purely tonemic marks (never seen in Sloleks dynamic layer; reserved for external tonemic data).
COMBINING_INVERTED_BREVE = "\u0311"
COMBINING_DOUBLE_GRAVE = "\u030F"

LENGTH_MARK = "ː"
PRIMARY_STRESS = "ˈ"

VOWELS = set("aeiouɛɔəAEIOU")

ACCENT_CLASS_VALUES = {"RL", "FL", "RS", "FS", "L", "S", "-"}


def _decompose(s: str) -> str:
    return unicodedata.normalize("NFD", s)


def detect_from_orthography(text: str) -> str:
    """Detect accent class from Sloleks dynamic accentuation (no tone info available).

    Returns L (long stressed), S (short stressed), or '-'. Upstream tonemic sources must upgrade
    L→RL/FL or S→RS/FS.
    """
    if not text:
        return "-"
    d = _decompose(text)
    for ch in d:
        if ch in (COMBINING_ACUTE, COMBINING_CIRCUMFLEX):
            return "L"
        if ch in (COMBINING_GRAVE, COMBINING_CARON):
            return "S"
        # Tonemic marks take priority if present (future-proof).
        if ch == COMBINING_INVERTED_BREVE:
            return "FL"
        if ch == COMBINING_DOUBLE_GRAVE:
            return "FS"
    return "-"


def detect_from_ipa(ipa: str) -> str:
    """Infer L/S from the IPA string based on stress mark + length mark.

    Returns L (long stressed), S (short stressed), or '-'. Tone can never be inferred from Sloleks
    IPA — that layer doesn't carry tonal information.
    """
    if not ipa:
        return "-"
    d = _decompose(ipa)
    if PRIMARY_STRESS not in d:
        return "-"
    start = d.index(PRIMARY_STRESS)
    end = len(d)
    for i in range(start + 1, len(d)):
        if d[i] in (PRIMARY_STRESS, "ˌ", " "):
            end = i
            break
    stressed_span = d[start:end]
    return "L" if LENGTH_MARK in stressed_span else "S"


def primary_stress_index(ipa: str) -> int:
    """0-based index of the stressed syllable, counting vowel-nuclei before ˈ.

    Returns -1 when no ˈ is present.
    """
    if not ipa or PRIMARY_STRESS not in ipa:
        return -1
    d = _decompose(ipa)
    stress_pos = d.index(PRIMARY_STRESS)
    prefix = d[:stress_pos]
    vowels_before = sum(1 for ch in prefix if ch in VOWELS)
    return vowels_before


def upgrade_tone(length_class: str, tone: str) -> str:
    """Merge a length class (L/S/-) with a tone (R/F/-) into a full SLPROS-1 accent_class.

    Used when external tonemic data is bound in.
    """
    if length_class not in ("L", "S"):
        return length_class
    if tone == "R":
        return "RL" if length_class == "L" else "RS"
    if tone == "F":
        return "FL" if length_class == "L" else "FS"
    return length_class
