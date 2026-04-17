# SL-Pron Static API Contract (v1)

Static, GitHub-Pages-compatible API. No server; the client loads gzipped JSON
artefacts via `fetch` and does all lookups in-process. Versioning is pinned
in `manifest.json`.

## Endpoints (static files)

| Path                           | Content                                   | Size (gz) |
|--------------------------------|-------------------------------------------|-----------|
| `/data/manifest.json`          | build id, sha1 of every artefact          | <2 kB     |
| `/data/words.json.gz`          | per-surface word entries (IPA, audio, …)  | ~53 kB    |
| `/data/sentences.json.gz`      | curated SL MVP corpus with SLPROS-1       | ~12 kB    |
| `/data/api/phrasebook.json.gz` | **EN→SL→SLPROS-1 lookup table**            | ~N MB     |
| `/data/api/phrasebook_index.json` | hash index for fast client-side matching | <100 kB   |
| `/data/audio_manifest.json`    | per-file audio metadata + licence          | ~30 kB    |
| `/data/validation_report.json` | scientific proofs (regressions, coverage) | ~20 kB    |

## Phrasebook record shape

```jsonc
{
  "id": "ph_0042",                   // stable per build
  "en": "Where is the train station?",
  "en_normalized": "where is the train station",  // lowercase + punctuation-stripped for lookup
  "sl": "Kje je železniška postaja?",
  "contour_type": "q_wh",
  "register": "formal",
  "coverage": 1.0,                   // fraction of tokens with IPA (must be 1.0 to ship)
  "tokens": [
    { "surface": "Kje", "ipa": "ˈkjeː", "upos": "ADV", "role": "content",
      "source": "sloleks", "sandhi_notes": [] },
    { "surface": "je",  "ipa": "ˈjɛ",   "upos": "AUX", "role": "clitic",
      "source": "sloleks", "sandhi_notes": ["R5:enclitic"] }
    // …
  ],
  "slpros1": {                       // full SLPROS-1 envelope (see slpros1_schema.json)
    "version": "SLPROS-1",
    "contour_type": "q_wh",
    "baseline_f0_hz": 180.0,
    "final_pause_ms": 500,
    "tokens": [ /* … */ ]
  },
  "speech_directive": {              // deterministic Web-Speech-API utterance spec
    "text": "Kje je železniška postaja?",
    "lang": "sl-SI",
    "rate": 1.0,                     // derived from SLPROS-1 mean duration
    "pitch": 1.0,                    // derived from SLPROS-1 baseline_f0_hz
    "volume": 1.0,
    "voice_preferences": [           // hint order for client voice selection
      "Microsoft Lado",              // Windows SL voice (if installed)
      "Google slovenščina",          // Chrome SL voice
      "sl-SI"                        // any voice with lang sl-SI
    ],
    "fallback": {
      "strategy": "concat_word_audio",   // when no SL voice available
      "alt_strategy": "espeak_wasm"      // last-resort IPA synthesis
    }
  },
  "provenance": {
    "translation_engine": "opus-mt-en-sla",
    "translation_prefix": ">>slv<<",
    "pipeline_version": "1.0.0",
    "generated_at": "2026-04-17T..."
  }
}
```

## Client usage (TypeScript)

```ts
// 1. Load once at app start
const manifest = await (await fetch('/data/manifest.json')).json();
const phrasebook: Record<string, PhrasebookRecord> =
    await loadGzipJson(`/data/api/phrasebook.json.gz`);

// 2. Exact-match lookup (fast O(1))
function lookupEn(enInput: string): PhrasebookRecord | null {
    const key = normalize(enInput);
    return phrasebook[key] ?? null;
}

// 3. Speak via Web Speech API
async function speakSL(rec: PhrasebookRecord): Promise<void> {
    const dir = rec.speech_directive;
    const utt = new SpeechSynthesisUtterance(dir.text);
    utt.lang = dir.lang;
    utt.rate = dir.rate;
    utt.pitch = dir.pitch;
    utt.volume = dir.volume;
    utt.voice = pickVoice(dir.voice_preferences);
    return new Promise((resolve, reject) => {
        utt.onend = () => resolve();
        utt.onerror = e => reject(e);
        speechSynthesis.speak(utt);
    });
}
```

## Guarantees (scientific constraints)

1. **Coverage**: every shipped record has `coverage == 1.0` — no token is
   served with missing IPA. Validated by `build/api/build_phrasebook.py`.
2. **Determinism**: the same `(en, pipeline_version)` pair always produces
   the same record. Manifest pins the version so clients can cache per-version.
3. **IPA provenance**: every token carries a `source` field ∈ {`sloleks`,
   `sloleks_lemma`, `grapheme`, `g2p`} so downstream audits can weight
   reliability.
4. **Sandhi applied**: every `token.ipa` is the post-sandhi form; the optional
   `sandhi_notes` list names the rules that fired.
5. **Web Speech API locked to Slovenian**: every `speech_directive.lang ==
   "sl-SI"`. Clients MUST NOT fall through to the browser-default voice if
   no sl-SI voice is installed; they MUST use the documented fallback chain
   (concatenative word-audio → eSpeak WASM) to avoid Polish/Russian/etc.
6. **Licence**: entire bundle inherits CC-BY-SA 4.0 from Sloleks 3.1.

## Versioning

`manifest.pipeline_version` is SemVer. MAJOR bump invalidates all client
caches. MINOR adds records without removing; PATCH fixes non-breaking IPA
or translation errors.
