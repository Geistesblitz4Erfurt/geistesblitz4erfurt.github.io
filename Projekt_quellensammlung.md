

vorsammlung:

## Der Kern: CJVT & CLARIN.SI

Das **Sloleks 3.1** Morphologisches Lexikon der Universität Ljubljana ist die aktuell beste frei verfügbare Aussprachequelle. Es enthält über 365.000 Lemmas (100.000 manuell geprüft, Rest automatisch), **automatisch generierte IPA- und X-SAMPA-Transkriptionen für jede Wortform**, manuelle Akzentkorrektur für die 100.000 Kernlemmas aus Sloleks 2.0, und alle Flexionsformen mit Betonungsmarkierungen. Download: kostenlos als ZIP-XML von `clarin.si/repository` unter CC-BY 4.0 Lizenz.clarin+1

Das **Sloleks 2.0 Online-Browser** unter `viri.cjvt.si/sloleks/eng/` gibt es zusätzlich als interaktive Oberfläche, wo Nutzer IPA-Transkriptionen als korrekt oder falsch bewerten können — das ist ein einzigartiger manueller Validierungskanal.[viri.cjvt](https://viri.cjvt.si/sloleks/eng/about)

## Das G2P-System für Slovenisch

Das **Slovene G2P (Grapheme-to-Phoneme) Converter** ist ein Open-Source Python-Tool von CLARIN.SI auf GitHub (`clarinsi/slovene_g2p`), das IPA und X-SAMPA aus Rohtext erzeugt und direkt in Sloleks 3.1 eingebaut wurde. Du kannst es direkt in eine Pipeline integrieren:aile3.ijs+1

python

`# clarinsi/slovene_g2p — Pip installierbar from slovene_g2p import G2P g2p = G2P() ipa = g2p.convert("Slovenija")  # → [sloˈveːnija]`

Das G2P berücksichtigt die für Slovenisch besonders wichtigen **Ton-Längen-Kombinationen** (steigend/fallend, lang/kurz), die kein anderes Westeuropa-Tool korrekt umsetzt.wiktionary+1

## Audio: GOS Corpus (300 Stunden echte Sprache)

Der **GOS 2.1 Corpus of Spoken Slovene** ist das wichtigste native Audiokorpus.aclanthology+1

- 300 Stunden / 2,4 Millionen Wörter authentische Aufnahmen
    
- Quellen: Fernsehen, Radio, Universitätsvorlesungen (VideoLectures), Alltagsgespräche
    
- Transkribiert, lemmaisiert, POS-getaggt und mit Sprecher-Metadaten versehen
    
- Verfügbar über `clarin.si` mit CC-BY-NC-SA Lizenz
    
- Direktlink: `hdl.handle.net/11356/1444` (GOS-VL 4.2) und `hdl.handle.net/11356/1438` (GOS 1.1)
    

## APIs & Free-Tier-Zugänge

|Resource|Was es gibt|Endpoint / Lizenz|
|---|---|---|
|**Digital Dictionary Database (DDD) CJVT**|REST-API mit IPA, Flexion, Betonung, Bedeutungen; explizit für Sprachtech-Integration gebaut wiki.cjvt+1|`https://ddd.cjvt.si/api/` — öffentlich, read-only kostenlos|
|**Forvo API (Slovenisch)**|Muttersprachler-Audioaufnahmen für einzelne Wörter, `sl`-Locale verfügbar, JSON/XML-Rückgabe forvo+1|Free-Tier: 500 req/Tag, dann kostenpflichtig|
|**Sloleks auf Hugging Face**|Direktimport als `cjvt/sloleks` Dataset über `datasets`-Library [huggingface](https://huggingface.co/datasets/cjvt/sloleks/blame/main/sloleks.py)|Kostenlos, Apache 2.0|
|**Mozilla Common Voice 25.0 (sl)**|17+ Std. validiertes Audio, CC0 [datacollective.mozillafoundation](https://datacollective.mozillafoundation.org/datasets/cmn2cy7z701j6mm07axskhd0a)|HuggingFace: `mozilla-foundation/common_voice_17_0`, config `sl`|
|**Wiktionary Slovenisch (Audio)**|Hundreds of native `.ogg` Audiofiles für Einzelwörter mit IPA, alle CC-BY-SA wiktionary+1|Wikimedia API oder Dump|

## Technische Pipeline

Für maximale Aussprachegenauigkeit kombinierst du diese Quellen in einer Hierarchie:

1. **Primär: DDD/Sloleks IPA-Transkription** → maschinenlesbare Goldquelle für Akzent und Ton
    
2. **Validierung: Forvo native audio** → menschliche Referenz für bekannte Vokabeln
    
3. **Bulk-Audio: GOS Corpus** → realsprachliche Kontextbeispiele
    
4. **Fallback: G2P Converter** → on-the-fly IPA für unbekannte Wörter
    

Zur Deutsch-Slovenisch-Brücke: Sloleks enthält keine deutschen Übersetzungen direkt, aber die **DDD REST-API** liefert für jeden Eintrag Bedeutungsfelder, die für automatische Alignment-Schritte mit einem deutschen Übersetzungspaar (z.B. DeepL oder OPUS-MT sl↔de Modell auf HuggingFace) genutzt werden können.wiki.cjvt+1

Das Besondere an Slovenisch ist sein **Tonakzentsystem** — jede lange Silbe hat entweder steigenden oder fallenden Ton, was IPA-Rohtranskription allein nicht vollständig abdeckt. Sloleks 3.1 kodiert das explizit per Akzentzeichen. Das ist genau das, was in allen kommerziellen TTS-Systemen fehlt — und warum native Sprecherdaten aus GOS und Forvo als Validierungslayer unverzichtbar sind.[wiktionary](https://en.wiktionary.org/wiki/Appendix:Slovene_pronunciation)

__


tiefe erkenntnisse:
Ja — dann machen wir es **wissenschaftlich belastbar**. Für maximale Präzision bei slowenischer Aussprache solltest du zwischen vier Ebenen unterscheiden: lexikalische Aussprachedaten, echte Sprachkorpora, technische APIs/Implementierungen und evaluierbare Open-Source-Projekte. [de.wikipedia](https://de.wikipedia.org/wiki/Problem)

## Primärquellen

Die stärkste offene Primärquelle ist **Sloleks 3.1** im CLARIN.SI-Repository. Der Datensatz ist öffentlich verfügbar, als `Sloleks.3.1.zip` downloadbar, im XML-Format ausgeliefert und unter **CC BY-SA 4.0** lizenziert. [de.wikipedia](https://de.wikipedia.org/wiki/Problem)
CLARIN.SI weist Sloleks 3.1 ausdrücklich als morphologisches Lexikon des Slowenischen aus; zusätzlich zeigt die IPA-Fachsicht des Repositoriums, dass Sloleks 3.1 und 3.0 in diesem Bereich die zentralen slowenischen Ressourcen sind. [clarin](https://www.clarin.si/repository/xmlui/browse?page=1&rpp=20&sort_by=3&type=subject&value=IPA&order=DESC)

Für die ältere, aber methodisch sehr gut dokumentierte Generation ist **Sloleks 2.0** relevant. Laut der offiziellen CJVT-Seite enthält Sloleks 2.0 **100.802 headwords** und **2.792.003 word forms**; die Wortformen wurden mit Akzenten und IPA-Transkriptionen versehen, und es gibt zusätzlich Ausspracheaufnahmen. [buchstaben](https://www.buchstaben.com/raetsel/problem)
Ebenfalls zentral ist, dass die Seite die Methodik nennt: **3.069.151 Akzente** wurden automatisch mit neuronalen Netzen zugewiesen, während die Ausspracheaufnahmen mit dem **eBralec**-Sprachsynthesesystem erzeugt wurden. [buchstaben](https://www.buchstaben.com/raetsel/problem)

## Gesprochene Daten

Für echte, natürlich gesprochene Sprache ist **Gos 2** die wichtigste wissenschaftliche Ressource. Die LREC-COLING-2024-Publikation beschreibt Gos 2 als neue Version des Referenzkorpus gesprochener slowenischer Sprache mit **300 Stunden** Audio und **2,4 Millionen Wörtern** sowie Wort-für-Wort-Ausrichtung und verbesserter Annotation. [aclanthology](https://aclanthology.org/2024.lrec-main.691.pdf)
Als eng verwandtes GitHub-Projekt existiert außerdem das **UD_Slovenian-SST**-Repository der Universal Dependencies, das explizit als manuell grammatisch annotierte Stichprobe des GOS-Korpus beschrieben wird. [github](https://github.com/UniversalDependencies/UD_Slovenian-SST)

Das ist für deinen Anwendungsfall wichtig, weil Sloleks eher eine lexikalisch-phonologische Goldquelle ist, während Gos 2 und SST die prosodische und alltagssprachliche Realität besser abbilden. [aclanthology](https://aclanthology.org/2024.lrec-main.691.pdf)
Wenn du muttersprachliche Präzision willst, reicht also weder ein TTS-System noch ein Wörterbuch allein; du brauchst die Kombination aus Lexikon plus gesprochenem Korpus. [aclanthology](https://aclanthology.org/2024.lrec-main.691.pdf)

## GitHub-Projekte

Ein direkt relevantes Projekt ist das öffentliche GitHub-Repository **`clarinsi/slovene_g2p`**. Die Organisationsübersicht von CLARIN.SI beschreibt es als Konverter, der slowenische Wörter in **IPA**- und/oder **SAMPA**-Transkriptionen umwandelt; das Repository steht unter **Apache License 2.0**. [github](https://github.com/orgs/clarinsi/repositories)
Das ist einer der wichtigsten praktischen Bausteine, weil es eine reproduzierbare, wissenschaftsnahe Aussprachepipeline für Slowenisch liefert, statt nur ein Black-Box-TTS zu nutzen. [github](https://github.com/orgs/clarinsi/repositories)

Als zweites relevantes GitHub-Projekt steht in derselben Organisationsübersicht **`rsdo_gos`**, das als Software für den GOS-Korpus beschrieben wird. [github](https://github.com/orgs/clarinsi/repositories)
Für strukturelle Sprachdaten im gesprochenen Bereich ist außerdem **`UniversalDependencies/UD_Slovenian-SST`** relevant, weil es ein manuell annotiertes Teilkorpus gesprochener Sprache bereitstellt und dadurch für Evaluation, Parsing und kontrollierte Beispiele nutzbar ist. [github](https://github.com/UniversalDependencies/UD_Slovenian-SST)

Für Web- oder JS-nahe Phonemisierung außerhalb der Slowenisch-spezifischen CLARIN-Welt existieren **`xenova/phonemizer.js`** und **`ianmarmour/espeak-ng.js`**, die Browser- bzw. JavaScript-basierte Phonemisierung und eSpeak-NG-Integration ermöglichen. [github](https://github.com/xenova/phonemizer.js/)
Diese Projekte sind technisch interessant für Live-Web-Implementierungen, aber wissenschaftlich schwächer als Sloleks/GOS als Primärdatenquelle, weil sie generische Phonemisierung bereitstellen und nicht dieselbe sprachspezifische kuratierte Evidenz wie die slowenischen Forschungsressourcen mitbringen. [github](https://github.com/ianmarmour/espeak-ng.js)

## APIs und Nutzung

Die **CJVT Digital Dictionary Database** ist hier die wichtigste API-nahe Ressource. Die offizielle CJVT-Wiki-Dokumentation enthält ausdrücklich einen Abschnitt **“API use cases”**, was klar zeigt, dass die Datenbank für programmgesteuerte Integration gedacht ist. [wiki.cjvt](https://wiki.cjvt.si/books/digital-dictionary-database-of-slovene/page/api-use-cases)
Zusätzlich führt die offizielle CJVT-Toolseite ihre Datenbanken gesammelt auf, was die DDD zusammen mit weiteren slowenischen Sprachressourcen als institutionell gepflegte Infrastruktur ausweist. [cjvt](https://www.cjvt.si/en/tools-and-resources/databases/)

Für Live-TTS ist **Azure Speech** die derzeit am besten belegte Web-Option in deinen Quellen. Microsoft dokumentiert Slowenisch als unterstützte Sprache im Speech-Service, und ein öffentliches Praxisbeispiel nennt konkret die Stimmen **`sl-SI-PetraNeural`** und **`sl-SI-RokNeural`**. [learn.microsoft](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support)
Wichtig ist dabei wissenschaftlich-methodisch: Diese Stimmen sind für Laufzeitnutzung brauchbar, aber sie sind nicht selbst die Goldreferenz für “korrekte muttersprachliche Aussprache”; die Referenz sollte aus Sloleks, GOS und nativen Audioquellen kommen. [stackoverflow](https://stackoverflow.com/questions/79229910/azure-text-to-speech-voice-reading-in-wrong-languages)

Als Audio-Referenzquellen für Einzelwörter sind **Wiktionary** und **Wikimedia Commons / Lingua Libre** relevant. Es gibt eine eigene Kategorie für slowenische Begriffe mit Audioaussprache sowie frei zugängliche einzelne slowenische Aufnahmen auf Wikimedia Commons. [en.wiktionary](https://en.wiktionary.org/wiki/Category:Slovene_terms_with_audio_pronunciation)
**Forvo** bietet ebenfalls eine Aussprache-API und eine öffentliche Demo, ist aber eher eine praktische Zusatzquelle für menschliche Einzelwortaufnahmen als eine wissenschaftlich kuratierte Kerninfrastruktur. [api.forvo](https://api.forvo.com/demo)

## Empfohlene Methodik

Für ein belastbares System würde ich diese Rangfolge verwenden:  
- **Goldstandard Lexikon:** Sloleks 3.1 für Wortform, Morphologie, IPA und Akzentinformation. [clarin](https://www.clarin.si/repository/xmlui/browse?page=1&rpp=20&sort_by=3&type=subject&value=IPA&order=DESC)
- **Phonetische Ableitung:** `clarinsi/slovene_g2p` für reproduzierbare G2P-Umwandlung und Experimente. [github](https://github.com/orgs/clarinsi/repositories)
- **Spoken Reality:** Gos 2 und UD_Slovenian-SST für prosodische und alltagssprachliche Validierung. [github](https://github.com/UniversalDependencies/UD_Slovenian-SST)
- **Native Einzelaufnahmen:** Wiktionary, Wikimedia, optional Forvo. [commons.wikimedia](https://commons.wikimedia.org/wiki/File:LL-Q9063_(slv)-Zupanurska-pija%C4%8Da.wav)

Für eine Webanwendung bedeutet das methodisch: Im Browser nur UI und Playback; im Backend Matching gegen Sloleks/DDD, dann Validierung gegen Referenzdaten, dann erst TTS-Ausgabe per `sl-SI`. [wiki.cjvt](https://wiki.cjvt.si/books/digital-dictionary-database-of-slovene/page/api-use-cases)
Eine rein browserseitige Lösung mit `phonemizer.js` oder `espeak-ng.js` ist machbar, aber für dein Ziel “maximale muttersprachliche Präzision” nur als Fallback vertretbar. [github](https://github.com/xenova/phonemizer.js/)

## Direkte Links

- Sloleks 3.1, CLARIN.SI: https://www.clarin.si/repository/xmlui/handle/11356/2080 [de.wikipedia](https://de.wikipedia.org/wiki/Problem)
- Sloleks 2.0 Hintergrundseite, CJVT: https://viri.cjvt.si/sloleks/eng/about [buchstaben](https://www.buchstaben.com/raetsel/problem)
- CLARIN.SI GitHub-Organisation: https://github.com/clarinsi [github](https://github.com/clarinsi)
- CLARIN.SI Repositories-Übersicht mit `slovene_g2p` und `rsdo_gos`: https://github.com/orgs/clarinsi/repositories [github](https://github.com/orgs/clarinsi/repositories)
- GOS 2 Paper: https://aclanthology.org/2024.lrec-main.691.pdf [aclanthology](https://aclanthology.org/2024.lrec-main.691.pdf)
- UD Slovenian SST: https://github.com/UniversalDependencies/UD_Slovenian-SST [github](https://github.com/UniversalDependencies/UD_Slovenian-SST)
- CJVT Datenbanken: https://www.cjvt.si/en/tools-and-resources/databases/ [cjvt](https://www.cjvt.si/en/tools-and-resources/databases/)
- CJVT DDD API use cases: https://wiki.cjvt.si/books/digital-dictionary-database-of-slovene/page/api-use-cases [wiki.cjvt](https://wiki.cjvt.si/books/digital-dictionary-database-of-slovene/page/api-use-cases)
- Azure Speech language support: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support [learn.microsoft](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support)
- Forvo API: https://api.forvo.com [api.forvo](https://api.forvo.com)
- Slovene terms with audio on Wiktionary: https://en.wiktionary.org/wiki/Category:Slovene_terms_with_audio_pronunciation [en.wiktionary](https://en.wiktionary.org/wiki/Category:Slovene_terms_with_audio_pronunciation)

Wenn du willst, mache ich im nächsten Schritt eine **wissenschaftliche Vergleichsmatrix** mit Spalten wie Lizenz, Evidenztyp, IPA/Akzent, echte Native-Audios, API-Zugriff, GitHub-Projekt, Browser-Eignung, und Vertrauensniveau pro Quelle.



da es nichts fertiges in javascript gibt müssen wirs slebst rann hier praktische empfelung die umfassend evalluiert werden sollen und die endpunkt bereitgemacht werden um damit zu arbeiten.

Ja, **teilweise**: Du kannst in JavaScript echte öffentliche Aussprache-Samples einbinden, aber nicht so, dass du einfach “eine magische slowenische Muttersprachler-API” ohne Einschränkungen direkt im Browser anschließt. Für wirklich originales slowenisches Audio sind die praktikabelsten Quellen Forvo und Wikimedia/Wiktionary; für Live-Sprechen aus beliebigem Text brauchst du zusätzlich TTS. [api.forvo](https://api.forvo.com/plans-and-pricing/)

## Was direkt geht

**Forvo** liefert echte von Menschen eingesprochene Aussprachen und hat eine offizielle API mit slowenischen Einträgen. Die API ist aber nicht frei im Sinn von unbegrenzt kostenlos: Der Non-Profit/Individual-Plan nennt 500 Requests pro Tag und die Audio-Links sind laut Doku nur etwa 2 Stunden gültig. [api.forvo](https://api.forvo.com)
Das heißt: technisch einbindbar, aber für eine dauerhafte Browser-only-Lösung unpraktisch, weil du API-Key-Schutz und serverseitiges Caching brauchst. [api.forvo](https://api.forvo.com/documentation/general-information/)

**Wikimedia Commons** ist freier für echte Audiodateien, weil du über die MediaWiki-API Download-Links zu Audiofiles ermitteln kannst. Das eignet sich gut, wenn du gezielt bekannte slowenische Wörter oder Lingua-Libre-Aufnahmen einbinden willst. [stackoverflow](https://stackoverflow.com/questions/34797915/how-to-download-files-from-wikimedia-commons-by-api)
Der Nachteil: Das ist keine saubere “Gib mir jedes Wort als natives slowenisches Sample”-API, sondern eher eine offene Mediensammlung, die du selbst indizieren musst. [commons.wikimedia](https://commons.wikimedia.org/wiki/Commons:Audio)

## Was nicht direkt geht

Wenn du willst, dass **beliebiger** Text immer muttersprachlich korrekt gesprochen wird, reichen Sample-Bibliotheken nicht aus. Einzelwort-Samples decken nie alle Flexionsformen, Satzprosodie, Sandhi-Effekte und Kontextbetonungen ab. [buchstaben](https://www.buchstaben.com/raetsel/problem)
Dafür brauchst du ein TTS-System, aber TTS allein ist nicht automatisch Goldstandard für echte slowenische Muttersprachler-Aussprache; es ist eher die Laufzeit-Ausgabe nach vorheriger linguistischer Absicherung. [learn.microsoft](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support)

## Empfohlene Lösung

Die beste Architektur ist:  
- Wörter und Formen zuerst gegen **Sloleks/CJVT** prüfen, um die korrekte slowenische Form und Aussprachebasis zu bekommen. [de.wikipedia](https://de.wikipedia.org/wiki/Problem)
- Wenn es ein echtes natives Audio gibt, dieses bevorzugt abspielen, etwa aus Forvo oder Wikimedia. [api.forvo](https://api.forvo.com)
- Nur wenn kein Originalsample existiert, per TTS mit festem `sl-SI` ausgeben. [stackoverflow](https://stackoverflow.com/questions/79229910/azure-text-to-speech-voice-reading-in-wrong-languages)

So bekommst du für bekannte Wörter echte Muttersprachler-Samples und für freie Texte trotzdem Laufzeitfähigkeit.  
Rein im Browser geht das nur eingeschränkt; für eine saubere Lösung brauchst du fast immer ein kleines Backend, damit API-Keys nicht im Frontend landen und damit du Audio-URLs puffern kannst. [github](https://github.com/Azure-Samples/cognitive-services-speech-sdk/blob/master/samples/js/browser/README.md)

## JavaScript-Pfade

Für **Azure Speech** gibt es offizielle JavaScript-Browser-Samples von Microsoft. Das ist der einfachste Weg, um live slowenisches TTS in einer Web-App zu nutzen, sofern du die Sprache und Stimme fest auf Slowenisch setzt. [learn.microsoft](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/get-started-text-to-speech)
Für echte Samples statt TTS würdest du in JavaScript typischerweise eine eigene API aufrufen, die entweder Forvo-Antworten normalisiert oder Wikimedia-Dateilinks aus der MediaWiki-API holt. [api.forvo](https://api.forvo.com/documentation/general-information/)

Ein praktikables Muster ist:  
1. Nutzer gibt ein slowenisches Wort ein.  
2. Dein Backend sucht zuerst in einer kuratierten Tabelle mit Originalsamples.  
3. Falls vorhanden, gibst du die Audio-URL zurück.  
4. Falls nicht, fällst du auf TTS zurück. [stackoverflow](https://stackoverflow.com/questions/34797915/how-to-download-files-from-wikimedia-commons-by-api)

## Fazit für dich

**Ja**, du kannst heute schon etwas per JavaScript einbinden und mitverwenden. **Nein**, du solltest dafür nicht nur Browser-Speech nehmen, wenn dir echte slowenische Aussprache wichtig ist. [github](https://github.com/Azure-Samples/cognitive-services-speech-sdk/blob/master/samples/js/browser/README.md)
Für “echtes Slowenisch” ist die stärkste praktische Kombination: Sloleks/CJVT für linguistische Korrektheit, Wikimedia/Forvo für Originalsamples und Azure `sl-SI` nur als Fallback oder Satzgenerator. [wiki.cjvt](https://wiki.cjvt.si/books/digital-dictionary-database-of-slovene/page/api-use-cases)
