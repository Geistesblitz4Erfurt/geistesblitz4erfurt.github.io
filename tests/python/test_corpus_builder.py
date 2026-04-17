from build.corpus.corpus_builder import build_corpus, extract_vocab


def test_build_corpus_yields_sentences():
    sentences = build_corpus()
    assert 140 <= len(sentences) <= 200, f"expected ~150, got {len(sentences)}"


def test_categories_present():
    sentences = build_corpus()
    cats = {s.category for s in sentences}
    assert cats == {"greeting", "food", "transport"}


def test_every_sentence_has_slovene_text():
    for s in build_corpus():
        assert s.sl and s.sl.strip()


def test_ids_are_unique():
    ids = [s.id for s in build_corpus()]
    assert len(ids) == len(set(ids))


def test_intonation_values_valid():
    valid = {"decl", "q_yn", "q_wh", "excl", "neutral"}
    for s in build_corpus():
        assert s.intonation in valid, f"{s.id} had intonation={s.intonation!r}"


def test_vocab_size_reasonable():
    vocab = extract_vocab(build_corpus())
    assert 100 < len(vocab) < 500


def test_known_tokens_present():
    vocab = extract_vocab(build_corpus())
    for tok in ("dober", "dan", "prosim", "hvala", "kje", "stane"):
        assert tok in vocab, f"expected token {tok!r} in corpus vocab"
