# Quellen & Lizenzen

## Primär-Ressourcen

| Quelle | Inhalt | URL | Lizenz | Nutzung |
|---|---|---|---|---|
| **Sloleks 3.1** | 372k Wortformen mit IPA+X-SAMPA+Akzent | https://www.clarin.si/repository/xmlui/handle/11356/2080 | CC-BY-SA 4.0 | Master-Lexikon, redistributable |
| **Sloleks 2.0** | 100k Kernlemmas mit manueller Akzentkorrektur | https://viri.cjvt.si/sloleks/eng/about | CC-BY-SA 4.0 | Cross-Validierung |
| **GOS 2** | 300h gesprochenes Slowenisch, lemmatisiert | https://aclanthology.org/2024.lrec-main.691.pdf | CC-BY-NC-SA 4.0 | **Nur Build-Validierung**, nicht redistribuiert |
| **CJVT DDD REST-API** | IPA, Flexion, Betonung, Bedeutung | https://wiki.cjvt.si/books/digital-dictionary-database-of-slovene/page/api-use-cases | öffentlich read-only | API-Cross-Check |
| **clarinsi/slovene_g2p** | Python G2P Konverter | https://github.com/clarinsi/slovene_g2p | Apache-2.0 | Fallback-Phonemisierung |

## Audio-Ressourcen

| Quelle | Inhalt | URL | Lizenz | Nutzung |
|---|---|---|---|---|
| **Wiktionary sl Audio** | Einzelwort-OGGs | https://en.wiktionary.org/wiki/Category:Slovene_terms_with_audio_pronunciation | CC-BY-SA 4.0 | Ausgeliefert in `/data/audio/words/` |
| **Lingua Libre** | Native-Speaker-Aufnahmen via Wikimedia Commons | https://lingualibre.org | CC-BY-SA 4.0 | Ausgeliefert |
| **Mozilla Common Voice sl 25.0** | 17+h validierte Aufnahmen | https://datacollective.mozillafoundation.org/datasets/cmn2cy7z701j6mm07axskhd0a | CC0 | Build-Referenz, optional bundle |
| **Forvo** | Native Einzelwort-Aufnahmen | https://api.forvo.com | proprietär, 500 req/Tag | **Nur Build-Validierung**, Audio nie gespeichert |

## Text-Ressourcen (Touristen-Korpus)

| Quelle | Inhalt | URL | Lizenz | Nutzung |
|---|---|---|---|---|
| Wikivoyage SL Phrasebook | Touristen-Kernsätze | https://en.wikivoyage.org/wiki/Slovenian_phrasebook | CC-BY-SA 3.0 | Seed für Templates |
| Leipzig Wortschatz sl | Frequenz-Ranking | https://wortschatz.uni-leipzig.de | CC-BY 4.0 | Frequenz-Metrik |
| Kaikki.org sl | Wiktionary-Extraktion | https://kaikki.org | CC-BY-SA 3.0 | Morpho-Cross-Check |

## Ausgabe-Lizenz

Alle Artefakte in `/data/` werden unter **CC-BY-SA 4.0** veröffentlicht, da Sloleks die stärkste
Copyleft-Klausel unter den direkt verwendeten Quellen hat. GOS (NC-SA) und Forvo (proprietär)
werden **nicht redistribuiert** — nur abgeleitete Validierungsmetriken gehen in
`/data/validation_report.json`, was ToS/Lizenz-konform ist (abgeleitete statistische Aussagen sind
keine Redistribution des Originalmaterials).

## Attribution-Pflicht

Jede Veröffentlichung muss enthalten:

- "Basiert auf Sloleks 3.1 (CJVT, CC-BY-SA 4.0)"
- "Audios teils aus Wiktionary/Lingua Libre (CC-BY-SA 4.0)"
- Volle Quellen-Liste in `data/LICENSE_ATTRIBUTION.md`

## Nicht genutzt (verworfen)

- Azure Speech Services sl-SI: ausgeschlossen laut User-Entscheidung (keine kostenpflichtigen APIs)
- Google Cloud TTS: dito
- Web Speech API als primäre Quelle: Qualität zu inkonsistent über Geräte
