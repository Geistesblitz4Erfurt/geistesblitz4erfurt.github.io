from build.normalize.ipa_normalizer import levenshtein, normalize, similarity


def test_normalize_collapses_alternates():
    assert normalize("[ˈgrad]") == "ˈɡrad"
    assert normalize("/ʧas/") == "t͡ʃas"


def test_normalize_whitespace():
    assert normalize("  ˈsloveːnija  ") == "ˈsloveːnija"


def test_levenshtein_basic():
    assert levenshtein("", "") == 0
    assert levenshtein("abc", "abc") == 0
    assert levenshtein("abc", "abd") == 1
    assert levenshtein("abc", "") == 3


def test_similarity_symmetric_and_bounded():
    s1 = similarity("ˈsloveːnija", "ˈsloveːnija")
    s2 = similarity("ˈsloveːnija", "sloveːnija")
    assert s1 == 1.0
    assert 0.8 < s2 < 1.0


def test_similarity_different_strings_low():
    assert similarity("ˈpes", "ˈmama") < 0.5
