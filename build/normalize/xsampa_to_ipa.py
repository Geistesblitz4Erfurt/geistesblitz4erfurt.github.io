"""X-SAMPA ↔ IPA conversion following the Sloleks convention.

Sloleks 3.1 emits both an ``xsampa`` and an ``ipa`` field per word-form. Having a bidirectional
mapping lets us verify consistency (each field should round-trip back to itself) and convert when
only one is present.

Table source: docs/PHONEME_TABLE.md (§ X-SAMPA Mapping) plus the standard X-SAMPA chart restricted
to Slovenian phonemes.
"""
from __future__ import annotations

# (xsampa, ipa) — ordered longest-first so greedy matching works.
_PAIRS: list[tuple[str, str]] = [
    ("tS", "t͡ʃ"),
    ("dZ", "d͡ʒ"),
    ("ts", "t͡s"),
    ("v\\", "ʋ"),
    (":", "ː"),
    ("\"", "ˈ"),
    ("%", "ˌ"),
    ("@", "ə"),
    ("E", "ɛ"),
    ("O", "ɔ"),
    ("S", "ʃ"),
    ("Z", "ʒ"),
    ("N", "ŋ"),
    ("J", "ɲ"),
    ("L", "ʎ"),
    ("r", "r"),
    ("R", "ʀ"),
    ("x", "x"),
    ("h", "h"),
    ("j", "j"),
    ("i", "i"),
    ("u", "u"),
    ("a", "a"),
    ("e", "e"),
    ("o", "o"),
    ("p", "p"),
    ("b", "b"),
    ("t", "t"),
    ("d", "d"),
    ("k", "k"),
    ("g", "ɡ"),
    ("f", "f"),
    ("s", "s"),
    ("z", "z"),
    ("m", "m"),
    ("n", "n"),
    ("l", "l"),
    ("v", "v"),   # fallback if v\ wasn't used
]

_XSAMPA_TO_IPA = dict(_PAIRS)
_IPA_TO_XSAMPA: dict[str, str] = {}
for x, i in _PAIRS:
    _IPA_TO_XSAMPA.setdefault(i, x)


def xsampa_to_ipa(s: str) -> str:
    """Greedy longest-match conversion X-SAMPA → IPA."""
    if not s:
        return ""
    out: list[str] = []
    i = 0
    while i < len(s):
        matched = False
        for x, ipa in _PAIRS:
            if s.startswith(x, i):
                out.append(ipa)
                i += len(x)
                matched = True
                break
        if not matched:
            out.append(s[i])
            i += 1
    return "".join(out)


def ipa_to_xsampa(s: str) -> str:
    """Best-effort IPA → X-SAMPA. Preserves diacritics and unknown characters verbatim."""
    if not s:
        return ""
    out: list[str] = []
    i = 0
    while i < len(s):
        matched = False
        for ipa, x in sorted(_IPA_TO_XSAMPA.items(), key=lambda kv: -len(kv[0])):
            if s.startswith(ipa, i):
                out.append(x)
                i += len(ipa)
                matched = True
                break
        if not matched:
            out.append(s[i])
            i += 1
    return "".join(out)
