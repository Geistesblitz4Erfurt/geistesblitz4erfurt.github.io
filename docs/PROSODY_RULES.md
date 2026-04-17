# SLPROS-1 — Slovenian Prosody Specification v1

Mathematisch explizite Beschreibung slowenischer Satzprosodie. Deterministisch, regel-basiert,
aus Sloleks-IPA-Einträgen + Satz-Kontext berechenbar. Keine KI. Schema: `build/prosody/slpros1_schema.json`.

## Motivation

Slowenisch hat ein aktives **Tonakzent-System** (dvojno naglaševanje): jede betonte lange Silbe hat
entweder steigenden oder fallenden Ton, kurze Silben nur einen einzigen Ton. Klassische
IPA-Rohtranskription reicht zur korrekten Synthese nicht aus — wir brauchen Längen-, Ton- und
F0-Kontur-Information pro Silbe, plus Satz-Kontur auf Phrasenebene.

## Datenmodell

Ein Satz = ein `SLPROS-1`-Objekt:

```
{version, contour_type, register, baseline_f0_hz, tokens[], final_pause_ms}
```

Ein Token = ein Wort (oder Interpunktion):

```
{surface, ipa, role, stress_syllable_idx, accent_class, syllables[], pause_after_ms, audio_asset_id, f0_contour_tag}
```

Eine Silbe = ein prosodisches Atom:

```
{phon, length, tone, dur_rel, f0_start_ct, f0_end_ct, is_stressed}
```

## Akzentklassen (`accent_class`)

| Code | Bedeutung | Beispiel | IPA |
|------|-----------|----------|-----|
| `RL` | Rising + Long | mésto (Stadt) | `[ˈmeːsto]` mit Akut |
| `FL` | Falling + Long | môst (Brücke) | `[ˈmoːst]` mit Circumflex |
| `RS` | Rising + Short | pès (Hund) | `[ˈpɛs]` mit Akut/Gravis |
| `FS` | Falling + Short | bràt (Bruder) | `[ˈbrât]` mit doppelter Gravis |
| `-`  | Unakzentuiert | Klitika, Funktionswörter | |

Quelle: Toporišič, *Slovenska slovnica* (4. Ausg. 2000); CJVT-Sloleks-Kodierung.

## Dauer-Modell

Silbenbaseline = 180 ms. `dur_rel` skaliert multiplikativ:

| Länge × Stress | `dur_rel` |
|---|---|
| Lang + betont (RL/FL) | 1.35 |
| Lang + unbetont | 1.10 |
| Kurz + betont (RS/FS) | 1.00 |
| Kurz + unbetont | 0.75 |
| Klitika | 0.60 |
| Finale Silbe vor Phrasen-Pause | × 1.15 (prä-pausale Dehnung) |

## F0-Kontur (Silben-Ebene)

Pitch-Offset in Cent (100 ct = ein Halbton) relativ zu `baseline_f0_hz` (standardmäßig 110 Hz
männlich / 200 Hz weiblich, aus `audio_asset.f0_baseline_hz`).

### Betonte Silbe
| Akzent | `f0_start_ct` | `f0_end_ct` |
|---|---|---|
| RL | +10 | +50 |
| FL | +40 | −40 |
| RS | +10 | +25 |
| FS | +25 | −15 |

### Unbetonte Silbe
| Position | `f0_start_ct` | `f0_end_ct` |
|---|---|---|
| Vor betonter | −5 | +0 |
| Nach betonter | +0 | −10 |
| Isoliert | −5 | −5 |

## Satz-Kontur (`contour_type`)

Skaliert die letzten ~3 Silben:

| Typ | Finaler Shift | Anwendung |
|---|---|---|
| `decl` | Letzte betonte Silbe −30 ct, finale Silbe −50 ct | Aussagesatz |
| `q_yn` | Letzte betonte Silbe +35 ct, finale Silbe +70 ct | Ja/Nein-Frage |
| `q_wh` | Flach-fallend: −15 ct über letzte 2 Silben | W-Frage |
| `excl` | Betonte Silbe +20 ct, finale Silbe −80 ct | Ausruf |
| `neutral` | Keine Modifikation | Debug/Einzelwörter |

## Pausen-Modell

| Auslöser | `pause_after_ms` |
|---|---|
| Komma | 120 |
| Phrasengrenze (Klitikakette beendet) | 250 |
| Satzgrenze (.! ?) | 500 (im `final_pause_ms`-Feld) |
| Zwischen Token ohne Interpunktion | 0–30 (Sandhi entscheidet) |

## Sandhi-Regeln (siehe `build/prosody/sandhi.py`)

1. **Proklitika-Kontraktion**: `v Ljubljani` → `[u‿ʎuˈblaːni]` (`v` → `[u]` vor stimmhaftem Konsonant)
2. **Vokalelision**: `že in` → `[ʒɛn]` bei schneller Rede (Register `informal`)
3. **Auslautverhärtung**: `grad` → `[ɡraːt]` (stimmhafter Obstruent am Wortende → stimmlos)
4. **Regressive Stimmhaftigkeits-Assimilation**: `oddaja` → `[oˈdːaja]`
5. **Präpositions-Klitik**: `na cesti` → `[naˈt͡sɛsti]` (Pro-Klitik bildet prosodische Einheit mit Host)

## Konsistenz-Invarianten (Validator-Checks)

- `stress_syllable_idx` < `len(syllables)`
- Genau eine Silbe mit `is_stressed = true` pro Content-Token (außer bei Komposita → erlaubt: mehrere)
- `accent_class != '-'` ⇔ `stress_syllable_idx >= 0`
- `|f0_start_ct|, |f0_end_ct|` ≤ 150 (kein Melisma über Oktave+)
- `sum(dur_rel × 180) + pause_after_ms` ≈ `duration_ms` des `audio_asset` (falls vorhanden, ±15%)
