# SL-Pron API — Licence & Attribution

The artefacts shipped under `/data/api/` inherit **CC-BY-SA 4.0** from the
Sloleks 3.1 lexicon. Redistribution of any subset is permitted under the
same licence with attribution preserved.

## Upstream sources

| Source | Version | Licence | Used for |
|---|---|---|---|
| Sloleks 3.1 (CJVT) | 3.1 (2022) | CC-BY-SA 4.0 | IPA + morphology master |
| Helsinki-NLP OPUS-MT `opus-mt-en-sla` | 2020-repo | CC-BY 4.0 | EN → SL translation (`>>slv<<` target prefix) |
| Helsinki-NLP OPUS-MT `opus-mt-sla-en` | 2020-repo | CC-BY 4.0 | Back-translation purity proof |
| UD Slovenian-SST | 2.16 | CC-BY-SA 4.0 | Regression / coverage ground-truth |
| clarinsi/slovene_g2p | Apache-2.0 | Apache-2.0 | G2P fallback (OOV words) |

## Citation

When redistributing or embedding, cite:

> Sloleks 3.1 — Krek, S., et al. CJVT, University of Ljubljana. CC-BY-SA 4.0.
> OPUS-MT — Tiedemann, J. *The Tatoeba Translation Challenge*. CC-BY 4.0.

## Derivative constraints

* Any work that bundles `/data/api/phrasebook.json.gz` **must** inherit
  CC-BY-SA 4.0 for the bundled file.
* The JavaScript client code in `/web/` is separately MIT-licensed and
  does not inherit CC-BY-SA; the boundary is the deserialized data.

## What is *not* in this bundle

Per licence compliance:

* No GOS 2 audio (CLARIN restricted).
* No ARTUR audio (CLARIN restricted).
* No Forvo audio (ToS).
* Common Voice SL — used only for timing regression validation, not
  redistributed.
