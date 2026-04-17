from build.prosody.contour_model import build_slpros1
from build.prosody.sandhi import SentenceTokens, Token, apply_sandhi


def _sent(pairs, register="formal"):
    return SentenceTokens(tokens=[Token(surface=s, ipa=i) for s, i in pairs], register=register)


def test_slpros1_single_word_decl():
    sent = _sent([("pes", "ˈpɛs")])
    apply_sandhi(sent)
    doc = build_slpros1(sent, contour_type="decl")
    assert doc["version"] == "SLPROS-1"
    assert doc["contour_type"] == "decl"
    assert len(doc["tokens"]) == 1
    tok = doc["tokens"][0]
    # Sloleks-derived accent_class without external tonemic data = S (short stressed)
    assert tok["accent_class"] == "S"
    assert tok["f0_contour_tag"] == "isolated"
    # exactly one stressed syllable
    assert sum(1 for s in tok["syllables"] if s["is_stressed"]) == 1


def test_slpros1_decl_final_fall():
    sent = _sent([("Dober", "ˈdɔːbɛr"), ("dan", "ˈdaːn")])
    apply_sandhi(sent)
    doc = build_slpros1(sent, contour_type="decl")
    final = doc["tokens"][-1]["syllables"][-1]
    # decl adds -50 ct to the final syllable end
    assert final["f0_end_ct"] < 0


def test_slpros1_yes_no_q_final_rise():
    sent = _sent([("Ali", "ˈali"), ("govorite", "ɡɔvɔˈriːtɛ")])
    apply_sandhi(sent)
    doc = build_slpros1(sent, contour_type="q_yn")
    final = doc["tokens"][-1]["syllables"][-1]
    # q_yn pushes final up by +70 ct
    assert final["f0_end_ct"] > 0


def test_clitic_has_no_stress():
    sent = _sent([("v", "v"), ("Ljubljani", "ʎubˈʎaːni")])
    apply_sandhi(sent)
    doc = build_slpros1(sent, contour_type="decl")
    v_tok = doc["tokens"][0]
    assert v_tok["accent_class"] == "-"
    assert v_tok["stress_syllable_idx"] == -1
    assert all(not s["is_stressed"] for s in v_tok["syllables"])


def test_prepausal_lengthening():
    sent = _sent([("pes", "ˈpɛs")])
    apply_sandhi(sent)
    doc = build_slpros1(sent, contour_type="decl")
    final_syll = doc["tokens"][-1]["syllables"][-1]
    # DUR_SHORT_STRESSED (1.0) × DUR_PREPAUSAL_MULTIPLIER (1.15) = 1.15
    assert abs(final_syll["dur_rel"] - 1.15) < 0.01


def test_all_bounded_f0():
    sent = _sent([("Slovenija", "sloˈveːnija")])
    apply_sandhi(sent)
    doc = build_slpros1(sent, contour_type="decl")
    for tok in doc["tokens"]:
        for s in tok["syllables"]:
            assert -150 <= s["f0_start_ct"] <= 150
            assert -150 <= s["f0_end_ct"] <= 150
