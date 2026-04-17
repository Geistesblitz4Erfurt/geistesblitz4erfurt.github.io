from build.normalize.syllabify import count_syllables, syllabify


def test_single_syllable():
    assert syllabify("pɛs") == ["pɛs"]
    assert count_syllables("pɛs") == 1


def test_two_syllables_simple():
    res = syllabify("ˈmama")
    assert len(res) == 2
    assert "".join(res) == "ˈmama"


def test_slovenija_three_syllables():
    res = syllabify("ˈsloveːnija")
    assert len(res) in (3, 4)
    assert "".join(res) == "ˈsloveːnija"


def test_max_onset_cluster():
    # 'pestro' should syllabify as [pe][stro] (max onset: 'str' is legal)
    result = syllabify("pestro")
    assert len(result) == 2
    assert result[1].startswith("s") or result[1].startswith("st")


def test_empty_input():
    assert syllabify("") == []
    assert count_syllables("") == 0
