# Web Speech API Contract (v1) — Slovenian Pronunciation Engine

> Normative source: **W3C Web Speech API Editor's Draft**
> <https://webaudio.github.io/web-speech-api/>
> Cross-checked against MDN Web Speech API tree (2026-04-17).

Every **shipped phrasebook record** carries a `speech_directive` object that
is a *complete, deterministic* specification of how the Web Speech API must
be invoked to produce **native-quality Slovenian** — never Croatian, Bosnian,
Serbian, Polish or Russian. This document is the contract between builder
and browser.

---

## 1. The W3C surface we depend on

| Interface | Role in this system |
|---|---|
| `window.speechSynthesis`                | Controller (`speak`, `cancel`, `pause`, `resume`, `getVoices`, `voiceschanged` event) |
| `SpeechSynthesisUtterance`              | One utterance: `text`, `lang`, `voice`, `rate`, `pitch`, `volume` + event handlers |
| `SpeechSynthesisVoice`                  | `voiceURI`, `name`, `lang`, `localService`, `default` |
| `SpeechSynthesisEvent` / `SpeechSynthesisErrorEvent` | Boundary/start/end/error callbacks |

We use **only speech synthesis**; `SpeechRecognition` is out of scope.

### 1.0 Canonical IDL (from W3C spec)

```webidl
[Exposed=Window]
interface SpeechSynthesis : EventTarget {
  readonly attribute boolean pending;
  readonly attribute boolean speaking;
  readonly attribute boolean paused;
  attribute EventHandler onvoiceschanged;
  undefined speak(SpeechSynthesisUtterance utterance);
  undefined cancel();
  undefined pause();
  undefined resume();
  sequence<SpeechSynthesisVoice> getVoices();
};

[Exposed=Window]
interface SpeechSynthesisUtterance : EventTarget {
  constructor(optional DOMString text);
  attribute DOMString text;
  attribute DOMString lang;
  attribute SpeechSynthesisVoice? voice;
  attribute float volume;     // [0..1],  default 1
  attribute float rate;       // [0.1..10], default 1
  attribute float pitch;      // [0..2],  default 1
  attribute EventHandler onstart;
  attribute EventHandler onend;
  attribute EventHandler onerror;
  attribute EventHandler onpause;
  attribute EventHandler onresume;
  attribute EventHandler onmark;
  attribute EventHandler onboundary;
};

[Exposed=Window]
interface SpeechSynthesisVoice {
  readonly attribute DOMString voiceURI;
  readonly attribute DOMString name;
  readonly attribute DOMString lang;
  readonly attribute boolean   localService;
  readonly attribute boolean   default;
};

[Exposed=Window]
interface SpeechSynthesisEvent : Event {
  readonly attribute SpeechSynthesisUtterance utterance;
  readonly attribute unsigned long charIndex;    // 0 if unsupported
  readonly attribute unsigned long charLength;   // 0 if unsupported
  readonly attribute float        elapsedTime;   // seconds; 0 if unsupported
  readonly attribute DOMString    name;          // "word" | "sentence" for boundary
};

[Exposed=Window]
interface SpeechSynthesisErrorEvent : SpeechSynthesisEvent {
  readonly attribute SpeechSynthesisErrorCode error;
};

enum SpeechSynthesisErrorCode {
  "canceled", "interrupted",
  "audio-busy", "audio-hardware", "network",
  "synthesis-unavailable", "synthesis-failed",
  "language-unavailable", "voice-unavailable",
  "text-too-long", "invalid-argument", "not-allowed"
};
```

### 1.1 Utterance property ranges (normative)

| Property   | Type   | Default | Range    | Our fixed value |
|------------|--------|---------|----------|-----------------|
| `text`     | string | `""`    | —        | post-sandhi SL surface string |
| `lang`     | string | `""`    | BCP-47   | **`"sl-SI"` — never anything else** |
| `voice`    | Voice  | `null`  | —        | picked from `voice_preferences` at runtime |
| `rate`     | number | `1.0`   | `0.1 – 10` | `1.0` (browser native cadence) |
| `pitch`    | number | `1.0`   | `0 – 2`    | `1.0` (SLPROS-1 encodes the real contour) |
| `volume`   | number | `1.0`   | `0 – 1`    | `1.0` |

`rate` and `pitch` are held at 1.0 *by design*: Slovenian tonemic / dynamic
accent is encoded per-syllable in `slpros1.tokens[].syllables[]`; a global
shift would flatten that information rather than refine it. Per-syllable F0
is enforced by the concat-audio fallback path, not by the Web Speech API
(which has no per-syllable pitch control).

### 1.2 Events we listen for

| Event       | Why |
|-------------|-----|
| `start`     | begin-of-speech spinner |
| `end`       | resolve playback promise |
| `error`     | reject + trigger fallback chain |
| `boundary`  | highlight current word (uses `charIndex`, `charLength`, `name`) |
| `pause` / `resume` | UI state sync |
| `mark`      | unused (SSML not served) |
| `voiceschanged` (on `speechSynthesis`) | re-run voice-picker once voices load |

---

## 2. Slovenian-purity enforcement

Four independent guards prevent non-Slovenian output:

### 2.1 Translation stage (build-time)
`build/translate/bridge.py` prepends the `>>slv<< ` target-language prefix
to every source text before `opus-mt-en-sla`. Without that prefix the
Slavic-multilingual checkpoint emits Bosnian or Croatian by default. This
is the *root* guarantee: any phrasebook record that survives translation is
Slovenian at the orthographic level.

### 2.2 Lexical verification (build-time)
`build/api/build_phrasebook.py` runs a character-set purity check on every
SL string before shipping:

* **Must-contain signal**: records that exceed 12 characters but contain
  *zero* Slovenian-specific graphemes (`č`, `š`, `ž`) are flagged for review.
* **Must-NOT-contain poisons**: reject Croatian `ć` / `đ`, Polish
  `ł` / `ą` / `ę` / `ń` / `ó` / `ś` / `ź` / `ż`, any Cyrillic codepoint,
  Serbian Latin `đ` / `ć`, Bosnian `ǉ` / `ǌ`. One hit → record dropped.
* **Whitespace-only / empty output**: dropped.

Counts of flags and drops appear in `build/_phrasebook_build_stats.json`
under `purity`.

### 2.3 Utterance configuration (runtime)
`speech_directive.lang === "sl-SI"` on **every** record. The spec requires
browsers to honour BCP-47; we never emit `sl_SI`, `slv`, or bare `sl`.

### 2.4 Voice selection (runtime)
`voice_preferences` is the ordered hint list the client must walk. The
client MUST:

1. After `voiceschanged`, call `speechSynthesis.getVoices()`.
2. Filter for voices whose `lang` **starts with** `sl` (BCP-47 subtag match).
3. Inside that filter, pick the first entry whose `name` or `voiceURI`
   contains any of the `voice_preferences` substrings (case-insensitive).
4. If **no** `sl*` voice exists, `speech_directive.fallback` takes over —
   the client MUST NOT let the UA auto-substitute an `en-*` / `hr-*` /
   `pl-*` / `ru-*` voice. The invariant
   `speech_directive.fallback.never_fall_back_to_other_language === true`
   is the kill-switch.

---

### 2.5 Error-code routing (normative)

The W3C `SpeechSynthesisErrorCode` enum has 12 values. Per
`speech_directive.error_handling`:

| Code                     | Client action          | Rationale |
|--------------------------|------------------------|-----------|
| `synthesis-unavailable`  | fall back chain        | engine missing |
| `synthesis-failed`       | fall back chain        | engine crashed |
| `language-unavailable`   | fall back chain        | no sl-SI voice |
| `voice-unavailable`      | fall back chain        | picked voice vanished |
| `audio-busy`             | fall back chain        | retry transient |
| `audio-hardware`         | fall back chain        | device missing |
| `network`                | fall back chain        | remote voice failed |
| `not-allowed`            | surface error UI       | user/UA blocked synthesis |
| `text-too-long`          | surface error UI       | our chunker must re-split |
| `invalid-argument`       | surface error UI       | build-time violation — file bug |
| `canceled` / `interrupted` | silent ignore        | caller issued cancel() |

`canceled` and `interrupted` are expected side-effects of `cancel()` — never
show these as failures.

### 2.6 Boundary events

When the `name` attribute of a `SpeechSynthesisEvent` fires on a `boundary`
event, it is exactly `"word"` or `"sentence"`. `charIndex`/`charLength`
index into `utterance.text` (zero-based, inclusive start). UAs that don't
support boundaries return `0` for both — clients must treat missing
boundaries as non-fatal.

## 3. Fallback chain

When no Slovenian voice is installed:

```
concat_word_audio      →  stitched Lingua-Libre / Wiktionary sample chain
  ↓ (missing samples)
espeak_wasm_sl         →  eSpeak-NG WASM with --voice=sl, IPA-driven
  ↓ (WASM disabled / no audio context)
audible_error          →  UI surface: "Slovenian voice unavailable"
```

Never `window.speechSynthesis.speak(...)` against a non-`sl` voice.

---

## 4. Chunking for the Chrome ~15 s bug

Chrome desktop silently stops synthesis after ≈ 15 s of audio. Phrasebook
records are single sentences (target < 8 s at rate 1.0) so this is not hit
in practice, but the directive carries `max_chunk_ms = 12000` as a client
hint. Clients building multi-sentence playback (e.g. paragraphs) MUST split
on punctuation and issue one utterance per chunk via `speak()` — the queue
handles ordering.

A keep-alive `pause()` + `resume()` every 10 s is the documented workaround
if chunking isn't possible; we don't require it for single-sentence records.

---

## 5. Minimal compliant client (TypeScript)

```ts
type SpeechDirective = {
  text: string;
  lang: "sl-SI";
  rate: 1.0;
  pitch: 1.0;
  volume: 1.0;
  voice_preferences: string[];
  fallback: {
    strategy: "concat_word_audio";
    alt_strategy: "espeak_wasm_sl";
    never_fall_back_to_other_language: true;
  };
  max_chunk_ms?: number;
  total_predicted_duration_ms: number | null;
};

async function voicesReady(): Promise<SpeechSynthesisVoice[]> {
  const synth = window.speechSynthesis;
  const now = synth.getVoices();
  if (now.length) return now;
  return new Promise((res) => {
    synth.addEventListener("voiceschanged", () => res(synth.getVoices()),
                          { once: true });
  });
}

function pickSlovenianVoice(
  voices: SpeechSynthesisVoice[],
  prefs: string[],
): SpeechSynthesisVoice | null {
  const sl = voices.filter(v => v.lang.toLowerCase().startsWith("sl"));
  if (!sl.length) return null;
  for (const needle of prefs) {
    const hit = sl.find(v =>
      v.name.toLowerCase().includes(needle.toLowerCase()) ||
      v.voiceURI.toLowerCase().includes(needle.toLowerCase()));
    if (hit) return hit;
  }
  return sl[0];
}

export async function speakSlovenian(dir: SpeechDirective): Promise<void> {
  const voices = await voicesReady();
  const voice  = pickSlovenianVoice(voices, dir.voice_preferences);
  if (!voice) {
    // STRICT: never substitute a non-sl voice
    return invokeFallback(dir);
  }
  const utt = new SpeechSynthesisUtterance(dir.text);
  utt.lang   = dir.lang;
  utt.voice  = voice;
  utt.rate   = dir.rate;
  utt.pitch  = dir.pitch;
  utt.volume = dir.volume;
  return new Promise((resolve, reject) => {
    utt.onend   = () => resolve();
    utt.onerror = e  => reject(e);
    window.speechSynthesis.speak(utt);
  });
}
```

---

## 6. Scientific guarantees (audit checklist)

| # | Claim | How proven |
|---|-------|-----------|
| 1 | Every shipped record is Slovenian text | `build_phrasebook.py` rejects Croatian/Polish/Russian graphemes before emit (§2.2); counts in `phrasebook_build_stats.purity`. |
| 2 | Every record has 100 % IPA coverage | `coverage == 1.0` gate in `build_phrasebook.py`. |
| 3 | Every record emits `lang="sl-SI"` | `_derive_speech_directive` hard-codes it; unit test `tests/python/test_speech_directive.py`. |
| 4 | No record can trigger a non-SL voice | `never_fall_back_to_other_language: True` flag + client spec §2.4. |
| 5 | API surface matches W3C spec | All six utterance properties populated at legal ranges (§1.1). |
| 6 | Chrome ≥ 15 s bug cannot silently truncate us | Per-record sentences well below threshold; `max_chunk_ms` advisory. |

Failures of 1–3 block the build; failures of 4–6 are regression tests in
`tests/web/` (Playwright).

---

## 7. Versioning

`speech_directive` shape is frozen under `pipeline_version` SemVer:
any removal or field-rename is a MAJOR bump, additive fields are MINOR.
Clients that cache artefacts by `manifest.pipeline_version` are safe.
