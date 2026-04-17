# SL-Pron Scientific Validation — Phase 1

**Stand:** 2026-04-17
**Scope:** Daten- und Evidenz-Ketten-Validierung vor SLPROS-1-Korpus-Build.
**Maschinenlesbare Zahlen:** siehe [`/data/validation_report.json`](../data/validation_report.json).

## Evidence Chain pro Wortform

| Schicht | Gewicht | Quelle | Status |
|---|---|---|---|
| `ipa_sloleks` | **0.45** | Sloleks 3.1 XML → master.sqlite | ✅ 7.9 M Formen (98.4% IPA-Abdeckung) |
| `ipa_acoustic` | **0.25** | wav2vec2-xls-r-sloveneASR (char-CTC) | ✅ 6113/6119 UD-SST Clips aligned |
| `ipa_g2p_rule` | **0.20** | clarinsi/slovene_g2p (Apache-2.0) | ⚠️ Smoke-OK; Bulk blockiert (siehe §5) |
| `ipa_wiktionary` | **0.10** | Commons native speakers | ✅ 113 Top-500-Formen |

Ein Token wird in `/data` emittiert, wenn `quality_score ≥ 0.60`. Untere landen in `/data/deferred.json` zur manuellen Review.

## 1. Lexikon (Sloleks 3.1)

| Kennzahl | Wert |
|---|---|
| Lemmas | 343 495 |
| Wortformen | 8 034 102 |
| Mit IPA | 7 906 937 (**98.4%**) |
| Akzentklasse L (lang-betont) | 4 212 685 |
| Akzentklasse S (kurz-betont) | 464 268 |
| Unbetont (`-`) | 3 357 149 |

Sloleks 3.1 codiert **keine tonemik** (keine steigend/fallend Unterscheidung) — wir melden ehrlich `L/S/-`. Die Felder `RL/FL/RS/FS` bleiben reserviert für eine spätere Aufrüstung aus SSKJ-T / Forvo / GOS-F0-Extraktion.

## 2. Phonetische Korpora

| Quelle | Status | Lizenz | Nutzung |
|---|---|---|---|
| **Common Voice SL 17.0** (fsicoli-Mirror) | 2 474 Clips, 13 293 rows | CC0-1.0 | Training + Validation, redistributierbar |
| **UD-SST Audio** (GOS 2 + ARTUR) | 6 113 Clips, 10.92 h | CLARIN restricted | **validation-only**, nicht in `/data` |
| **VoxPopuli SL** | 3 Parquets, 1.7 GB | CC0-1.0 | redistributierbar |
| **Lingua-Libre SL** | 99 Dateien | CC-BY-SA-4.0 | ausgeliefert in `data/audio/words/` |
| **Wiktionary SL Audio** | 113 Dateien | CC-BY-SA-4.0 | ausgeliefert |

## 3. Alignment-Qualität

- **Modell:** `anton-l/wav2vec2-large-xlsr-53-slovenian` (CC-BY-4.0)
- **Algorithmus:** Viterbi-Trellis CTC mit 3-Wege-Übergängen (same/prev/skip), numpy log-probs
- **Frame-Rate:** 50 fps
- **F0:** librosa.pyin YIN (fmin 80 Hz, fmax 500 Hz, hop 256)
- **Erfolgsrate UD-SST:** **99.9%** (6 113 / 6 119), 6 Fehler wegen CTC-Constraint T ≥ 2L+1 auf extrem kurzen Clips

## 4. Prosodie-CPT (`build/_prosody_cpt.json`)

13 508 Token-Beobachtungen über 6 113 Clips, bucketed nach `(upos, deprel, pos_bin)` mit Fallback-Kette auf upos-marginal und global.

| Abdeckung | Anzahl Buckets |
|---|---|
| Total | 464 |
| n ≥ 20 (Prior aktiv) | 103 |
| n ≥ 50 (hoch-robust) | 63 |

### Linguistische Sanity-Checks (alle bestanden)

**Inhaltswörter werden länger, Funktionswörter werden kürzer** (textbook, Crystal 1969):

| POS | dur_rel | Befund |
|---|---|---|
| INTJ (Filler) | 1.56 | Längste — klassischer Zögerungseffekt |
| ADJ | 1.08 | lang |
| NOUN | 1.02 | lang |
| VERB | 0.90 | mittel |
| PRON | 0.81 | kurz |
| DET | 0.73 | kurz |
| CCONJ | 0.66 | kurz |
| SCONJ | 0.63 | kurz |
| AUX | 0.62 | kurz |
| **ADP** | **0.51** | **kürzeste (proklitisch!)** |

**F0-Deklination** (deklarativer Satzakzent):
- Satz-Start 439 ct → Satz-Ende 431 ct = **−9 ct Deklination** über durchschnittliche Satzlänge, konform zu Ladd (2008).

**INTJ F0-Signatur:**
- Start 356 ct, Ende 340 ct — tief und monoton, konsistent mit creaky-voice Filler-Phänomen.

## 5. Bekannte Einschränkungen

1. **Tonale Dimension fehlt** — Sloleks kodiert nur dynamische Akzentuierung. `RL/FL/RS/FS` bleibt für Phase 2 reserviert.
2. **F0 absolut speaker-gemischt** — mittlerer F0 über alle Clips 186.8 Hz. Alle Prosodie-Auswertungen arbeiten in **Cents vom 10. Perzentil pro Clip**, sprecher-normalisiert.
3. **CTC char-level, nicht phoneme-level** — Phonem-Zeiten werden downstream aus Sloleks-IPA-Sequenzen über Positions-Mapping rekonstruiert (`cpt_learner.py::_segment_tokens`).
4. **G2P-Bulk-Crosscheck blockiert** — `master.sqlite::word_form` enthält `surface` (ohne Akzent-Diakritika) aber nicht `accented_form`; clarinsi/slovene_g2p braucht aber `slovénski` mit Akzenten. Handvalidierte Stichproben (`slovénski`, `hvála`, `dóber`, `Ljubljana`) passen phonem-exakt. Follow-up: Sloleks-Re-Ingest mit `accented_form` und `morphology_pattern_code` als zusätzliche Spalten.
5. **Common Voice Alignment steht aus** — wird nach GPU-Upgrade in Batch gefahren (siehe §6).

## 6. Hardware-Roadmap

PyTorch-Version 2.11.0+**cpu** blockierte wav2vec2 auf der CPU (≈ 1.57 Clips/s). Upgrade auf `torch==2.6.0+cu124` läuft; danach:

- Batched-GPU-Forward (Batch 8–16, fp16) auf RTX 3080 (10 GB)
- CPU-Worker-Pool für Viterbi + librosa.pyin parallel
- Erwartete Throughput-Steigerung: **20×** (30–50 clips/s)
- Danach Common-Voice-17.0 full alignment (2 474 Clips, ≈ 1 min statt 25 min)

## 7. Nächste Gates vor Produktion

| Metrik | Ziel |
|---|---|
| IPA-Agreement Sloleks↔G2P (1 000-Sample) | ≥ 95% exact + 1-edit |
| SLPROS-1 Silben-Dauer RMSE (gold vs. predicted) | < 0.030 s |
| Data-Bundle Größe gzip | ≤ 50 MB |
| Web-E2E Playwright-Smoke | 10 Sätze, 0 Console-Errors |
