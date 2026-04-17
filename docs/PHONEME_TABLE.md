# Slovenisches Phonem-Inventar (normativ)

Grundlage: Toporišič *Slovenska slovnica* (2000), Šuštaršič/Komar/Petek (1999) "Slovene" in
*Handbook of the IPA*, CJVT-Sloleks 3.1 Normalisierungstabellen, Wiktionary sl-IPA-Help.

Zielnorm: **zentralslowenisch / Ljubljana-Standard** (identisch zur Sloleks-Kodierung).

## Vokale (8 Qualitäten + Reduktion)

| IPA | X-SAMPA | Beispiel | Gloss | Dauer |
|-----|---------|----------|-------|-------|
| `i` | `i` | *mi* | wir | lang möglich |
| `iː` | `i:` | *sin* | Sohn | lang |
| `eː` | `e:` | *pes* | Hund | lang (nur betont) |
| `ɛ` | `E` | *mesto* | Stadt (kurz) | kurz |
| `ɛː` | `E:` | *mêst* | gen.pl. | lang + fallend |
| `a` | `a` | *pas* | Gürtel | kurz |
| `aː` | `a:` | *mál* | wenig | lang |
| `ɔ` | `O` | *potok* | Bach | kurz |
| `ɔː` | `O:` | *môst* | Brücke | lang + fallend |
| `oː` | `o:` | *bóg* | Gott | lang + steigend |
| `u` | `u` | *kup* | Haufen | kurz |
| `uː` | `u:` | *núnc* | Onkel | lang |
| `ə` | `@` | *pes* (wenn reduziert), *mrtev* | Schwa | nur unbetont/silbisches R-Assistenz |

**Hinweis:** Slowenisch unterscheidet `ɛ/eː` und `ɔ/oː` **nur** in betonten langen Silben.
In unbetonten Silben reduzieren sie sich zu `ɛ`/`ɔ` (Mittellagen).

## Konsonanten (21 Phoneme)

### Plosive
| stimmlos | stimmhaft | IPA | Beispiel |
|---|---|---|---|
| `p` | `b` | — | *pas / bas* |
| `t` | `d` | — | *ta / da* |
| `k` | `ɡ` | — | *kos / gost* |

### Frikative
| stimmlos | stimmhaft | Beispiel |
|---|---|---|
| `f` | `ʋ` / `v` | *forma / voda* |
| `s` | `z` | *sin / zid* |
| `ʃ` | `ʒ` | *šuma / žena* |
| `x` | — | *hiša* |

### Affrikaten
| IPA | X-SAMPA | Beispiel |
|---|---|---|
| `t͡s` | `ts` | *cesta* |
| `t͡ʃ` | `tS` | *čas* |
| `d͡ʒ` | `dZ` | *džezva* (Lehnwort) |

### Nasale
| `m` | `n` | `ɲ` (<nj>) |
|---|---|---|
| *mama* | *nos* | *konj* |

### Liquide
| `l` | `ʎ` (<lj>) | `r` |
|---|---|---|
| *lep* | *polje* | *rok* |

### Approximant
| `j` (<j>) |
|---|
| *jaz* |

## Konsonanten-Allophone

| Kontext | Regel | Beispiel |
|---|---|---|
| `v` vor Vokal | → `[ʋ]` | *voda* `[ˈʋoːda]` |
| `v` vor stimmhaftem Konsonant | → `[u]` (pro-klitisch) | *v Ljubljani* `[uʎuˈblaːni]` |
| `v` vor stimmlosem Konsonant | → `[f]` (pro-klitisch) | *v petek* `[fˈpɛːtɛk]` |
| `v` Wortende nach Vokal | → `[u̯]` (Diphthong-Element) | *siv* `[siːu̯]` |
| `l` Wortende oder vor Konsonant | → `[u̯]` | *bil* `[biːu̯]` |
| Stimmhafter Obstruent Wortende | → stimmlos | *grad* `[ɡraːt]` |

## Akzent-Diakritika (tonemisch)

| Unicode | Name | Bedeutung (tonemisch) |
|---|---|---|
| ◌́ | Acute (U+0301) | Langer steigender Ton (RL) |
| ◌̑ | Inverted Breve (U+0311) | Langer fallender Ton (FL) |
| ◌̀ | Grave (U+0300) | Kurzer steigender Ton (RS) oder kurzer betonter Schwa |
| ◌̏ | Double Grave (U+030F) | Kurzer fallender Ton (FS) |
| ː | Length Mark (U+02D0) | Vokallängung im IPA |

**In Sloleks 3.1**: Alle vier Diakritika erscheinen in der orthographischen Akzentschreibung
(Wörterbuch-Schreibung). Im IPA-Feld wird Ton durch Diakritika über dem Vokalzeichen plus `ː`
für Länge markiert.

## X-SAMPA Mapping (Sloleks-Konvention)

Sloleks liefert parallel X-SAMPA + IPA. Für Konversion:

| IPA | X-SAMPA |
|---|---|
| `ɛ` | `E` |
| `ɔ` | `O` |
| `ə` | `@` |
| `ʃ` | `S` |
| `ʒ` | `Z` |
| `t͡ʃ` | `tS` |
| `t͡s` | `ts` |
| `d͡ʒ` | `dZ` |
| `x` | `x` |
| `ʋ` | `v\` (sic: X-SAMPA für labiodentalen Approximant) |
| `ʎ` | `L` |
| `ɲ` | `J` |
| `ː` | `:` |
| ˈ (primary stress) | `"` |
| ˌ (secondary stress) | `%` |

Vollständige Mapping-Tabelle in [`build/normalize/xsampa_to_ipa.py`](../build/normalize/xsampa_to_ipa.py).

## Silbenstruktur

Slowenisch erlaubt komplexe Anlaute: maximal **CCCV(C)(C)(C)** (z.B. *stric* `[striːt͡s]`,
*vprašati* `[uˈpraːʃati]`). Silbifizierungs-Algorithmus (Maximum-Onset-Prinzip):

1. Vokale sind Silbenkerne; Schwa `ə` nur als Kern wenn silbisches `r̩` (geschrieben <r>).
2. Konsonanten zwischen zwei Vokalen: maximal viele zum folgenden Onset, sofern Onset-Cluster
   am Wortanfang legal ist.
3. Silbisches `r` zählt als Kern: `prst` → `[pr̩st]` (eine Silbe).

Implementierung: `build/normalize/syllabify.py` (Regel-basiert, keine Statistik).
