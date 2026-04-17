import unicodedata

from build.normalize.accent_decoder import (
    detect_from_ipa,
    detect_from_orthography,
    primary_stress_index,
    upgrade_tone,
)


def _compose(base: str, diacritic: str) -> str:
    return unicodedata.normalize("NFC", base + diacritic)


# Sloleks 3.1 dynamic accentuation layer does NOT encode tone, only stress + length.
# We emit L/S length classes from orthographic marks; tone must come from an external source.


def test_orthography_acute_long_stressed():
    # 'á' — combining acute over 'a' → long stressed (tone unknown)
    assert detect_from_orthography(_compose("a", "\u0301")) == "L"


def test_orthography_circumflex_long_stressed_variant():
    # 'â' — combining circumflex (legacy/variant long marker in Sloleks dynamic)
    assert detect_from_orthography(_compose("a", "\u0302")) == "L"


def test_orthography_grave_short_stressed():
    assert detect_from_orthography(_compose("a", "\u0300")) == "S"


def test_orthography_caron_short_stressed_variant():
    assert detect_from_orthography(_compose("a", "\u030C")) == "S"


def test_orthography_tonemic_inverted_breve_long_falling():
    # Future-proof: if external data uses U+0311, we upgrade to FL immediately
    assert detect_from_orthography(_compose("a", "\u0311")) == "FL"


def test_orthography_tonemic_double_grave_short_falling():
    assert detect_from_orthography(_compose("a", "\u030F")) == "FS"


def test_orthography_no_diacritic():
    assert detect_from_orthography("dan") == "-"


def test_ipa_long_stressed():
    assert detect_from_ipa("ˈsloveːnija") == "L"


def test_ipa_short_stressed():
    assert detect_from_ipa("ˈpɛs") == "S"


def test_ipa_unstressed_returns_dash():
    assert detect_from_ipa("sloveːnija") == "-"


def test_primary_stress_index():
    assert primary_stress_index("ˈpɛs") == 0
    assert primary_stress_index("sloˈveːnija") == 1
    assert primary_stress_index("bez_mark") == -1


def test_upgrade_tone_long():
    assert upgrade_tone("L", "R") == "RL"
    assert upgrade_tone("L", "F") == "FL"
    assert upgrade_tone("L", "-") == "L"


def test_upgrade_tone_short():
    assert upgrade_tone("S", "R") == "RS"
    assert upgrade_tone("S", "F") == "FS"


def test_upgrade_tone_noop_on_dash():
    assert upgrade_tone("-", "R") == "-"
