from build.normalize.xsampa_to_ipa import ipa_to_xsampa, xsampa_to_ipa


def test_single_chars():
    assert xsampa_to_ipa("S") == "ʃ"
    assert xsampa_to_ipa("E") == "ɛ"
    assert xsampa_to_ipa("O") == "ɔ"


def test_compound_affricates():
    assert xsampa_to_ipa("tS") == "t͡ʃ"
    assert xsampa_to_ipa("dZ") == "d͡ʒ"
    assert xsampa_to_ipa("ts") == "t͡s"


def test_length_stress():
    assert xsampa_to_ipa('"a:') == "ˈaː"


def test_labiodental_approximant():
    assert xsampa_to_ipa("v\\oda") == "ʋoda"


def test_roundtrip_ipa_to_xsampa():
    assert ipa_to_xsampa("ˈʃɔla") == '"SOla'
    assert ipa_to_xsampa("t͡ʃas") == "tSas"


def test_unknown_chars_preserved():
    # X-SAMPA 'Z' maps to IPA ʒ, 'Y' has no mapping so it stays as-is.
    assert xsampa_to_ipa("XYZ") == "XYʒ"
