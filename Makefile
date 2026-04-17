.PHONY: all fetch build validate compile clean test help

PY := python
SQLITE := build/master.sqlite

help:
	@echo "Targets:"
	@echo "  fetch     - Download Sloleks 3.1 + Wiktionary audios (large!)"
	@echo "  build     - Parse sources into SQLite master + build corpus"
	@echo "  validate  - Run cross-check validators"
	@echo "  compile   - Emit /data/*.json.gz + audio manifest"
	@echo "  test      - Run pytest suite"
	@echo "  clean     - Remove build artifacts (keeps sources/)"
	@echo "  all       - fetch + build + validate + compile"

all: fetch build validate compile

fetch:
	$(PY) -m build.ingest.fetch_sloleks
	$(PY) -m build.ingest.wiktionary_audio_fetch
	$(PY) -m build.ingest.lingualibre_fetch

build: $(SQLITE)

$(SQLITE):
	$(PY) -m build.ingest.sloleks_parser --out $(SQLITE)
	$(PY) -m build.normalize.accent_decoder --db $(SQLITE)
	$(PY) -m build.corpus.corpus_builder --db $(SQLITE)
	$(PY) -m build.prosody.contour_model --db $(SQLITE)
	$(PY) -m build.audio.pre_render --db $(SQLITE)

validate:
	$(PY) -m build.validate.validate_ipa_agreement --db $(SQLITE)
	$(PY) -m build.validate.validate_accent_consistency --db $(SQLITE)
	$(PY) -m build.validate.validate_audio_duration --db $(SQLITE)

compile:
	$(PY) -m build.compile.emit_json --db $(SQLITE) --out data/
	$(PY) -m build.compile.emit_audio_manifest --db $(SQLITE) --out data/

test:
	pytest tests/python/ -v

clean:
	rm -f $(SQLITE) $(SQLITE)-journal
	rm -f data/*.json.gz
	rm -rf data/audio/
	find build -name "__pycache__" -exec rm -rf {} +
