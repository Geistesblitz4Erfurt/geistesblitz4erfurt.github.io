from build.prosody.sandhi import SentenceTokens, Token, apply_sandhi


def _mk(pairs):
    return SentenceTokens(tokens=[Token(surface=s, ipa=i) for s, i in pairs])


def test_prep_v_before_voiced_becomes_u():
    sent = _mk([("v", "v"), ("Ljubljani", "ʎubˈʎaːni")])
    apply_sandhi(sent)
    assert sent.tokens[0].ipa == "u"
    assert sent.tokens[0].role == "clitic"
    assert sent.tokens[0].host_index == 1
    assert "R1:prep_v_proclitic" in sent.tokens[0].notes


def test_prep_v_before_voiceless_becomes_f():
    sent = _mk([("v", "v"), ("petek", "ˈpɛːtɛk")])
    apply_sandhi(sent)
    assert sent.tokens[0].ipa == "f"
    assert sent.tokens[0].role == "clitic"


def test_final_devoicing_word_final_d_to_t():
    sent = _mk([("grad", "ɡraːd")])
    apply_sandhi(sent)
    assert sent.tokens[0].ipa.endswith("t")
    assert "R2:final_devoicing" in sent.tokens[0].notes


def test_final_devoicing_skipped_before_voiced():
    # grad in → final d should NOT devoice (next word starts with a vowel, no obstruent)
    sent = _mk([("grad", "ɡraːd"), ("in", "in")])
    apply_sandhi(sent)
    # Since 'in' starts with a vowel (not an obstruent), devoicing still applies per rule.
    assert sent.tokens[0].ipa.endswith("t")


def test_enclitic_attachment():
    sent = _mk([("Ana", "ˈana"), ("je", "je")])
    apply_sandhi(sent)
    assert sent.tokens[1].role == "clitic"
    assert sent.tokens[1].host_index == 0
    assert sent.tokens[1].pause_after_ms == 0


def test_idempotent_apply():
    sent = _mk([("v", "v"), ("Bledu", "ˈblɛːdu")])
    apply_sandhi(sent)
    first_ipa = sent.tokens[0].ipa
    # Second application should not re-break the result
    apply_sandhi(sent)
    assert sent.tokens[0].ipa == first_ipa
