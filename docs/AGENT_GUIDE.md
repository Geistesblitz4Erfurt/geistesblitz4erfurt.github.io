# SL-Pron — Agent Guide

For LLMs, IDEs, and other machine consumers.

## Invariant rules (hold for every response)

1. **⟶ NEXT convention.** Every message you generate about SL-Pron ends
   with a single line `⟶ NEXT: <concrete next tool call or file to touch>`.
   No exceptions — this keeps the loop deterministic and auditable.
2. **Minimum three independent sources** per token before you trust it:
   Sloleks IPA, slovene_g2p, and either audio alignment or back-translation.
   A single layer is never enough.
3. **IPA always next to orthography.** Never print a Slovenian word to a
   user without its IPA in `/slashes/`. The phonetic is primary, the
   orthography is display.
4. **Never fall back out of Slovenian.** If no `sl-*` voice is available,
   surface the error — do not use an English/German voice as a substitute.
5. **Deterministic prosody.** SLPROS-1 is rule-based; do not add stochastic
   TTS parameters. Pass `speech_directive` verbatim.

## REST cookbook (the local HTTP server)

Base URL: `http://127.0.0.1:8765/` (run `python -m serve.test_server`).

### Look up / synthesize

```bash
curl -s "http://127.0.0.1:8765/api/synthesize?en=Good+morning."
```

Returns either `{"lookup":"phrasebook", ...}` (O(1)) or `{"lookup":"live", ...}`
(full pipeline). The payload always contains:

- `sl` — Slovenian text
- `tokens[].ipa` — per-token IPA (post-sandhi)
- `speech_directive` — drop-in for `SpeechSynthesisUtterance`
- `slpros1` — per-syllable duration + F0 envelope

### Validate a candidate word

```bash
curl -s -X POST http://127.0.0.1:8765/api/validate_word \
  -H "Content-Type: application/json" \
  -d '{"en":"house","sl":"hiša"}'
```

Returns `score`, `layer_results` (L1–L6), and `persisted ∈ {verified_extensions, pending_audit, null}`.

### Audit submit (machine-originated feedback)

```bash
curl -s -X POST http://127.0.0.1:8765/api/audit_submit \
  -H "Content-Type: application/json" \
  -d '{"id":"Good morning.|Dobro jutro.","verdict":"ok","note":"spot-check passed"}'
```

### Live stats

```bash
curl -s http://127.0.0.1:8765/api/stats
```

### Paginate pending / verified

```bash
curl -s "http://127.0.0.1:8765/api/pending_audit?limit=50"
curl -s "http://127.0.0.1:8765/api/verified?since=2026-04-17T00:00:00Z"
```

## MCP cookbook (Claude Desktop, Claude Agent SDK)

Install once:

```bash
pip install mcp
# Add mcp_server/manifest.json → claude_desktop_config_snippet
# into your Claude Desktop config file.
```

Available tools:

| Tool | Input | Output |
|---|---|---|
| `lookup_phrase` | `{en}` | `{found, record?, next}` |
| `translate_and_speak` | `{en}` | `{source, record, next}` |
| `validate_word` | `{en, sl, ipa?}` | `{score, layers, persisted, next}` |
| `list_categories` | `{}` | `{total_records, categories, next}` |
| `get_phonetic` | `{sl}` | `{ipa, syllables, stress_syllable_idx, next}` |

### Minimal agent loop

```text
1. lookup_phrase(en=user_input)
2. if not found: translate_and_speak(en=user_input)
3. if coverage < 1.0 on a token: validate_word(en=word.en_gloss, sl=word.sl)
4. render: f"{sl} /{ipa}/" (rule 3)
5. emit ⟶ NEXT
```

## Browser integration (Web Speech API)

```js
const r = await fetch('/api/synthesize?en=' + encodeURIComponent(en));
const rec = await r.json();
const dir = rec.speech_directive;               // never mutate this
const voices = speechSynthesis.getVoices();
const voice = voices.find(v =>
  v.lang.toLowerCase().startsWith('sl') &&
  dir.voice_preferences.some(p => v.name.includes(p))
) || voices.find(v => v.lang.toLowerCase().startsWith('sl'));
if (!voice) throw new Error('no-sl-voice');     // rule 4

const u = new SpeechSynthesisUtterance(dir.text);
u.lang = dir.lang;                              // "sl-SI"
u.voice = voice;
u.rate = dir.rate;  u.pitch = dir.pitch;  u.volume = dir.volume;
u.onerror = e => console.warn(e.error);
speechSynthesis.speak(u);
```

### Error-code routing (from `speech_directive.error_handling`)

| Bucket | Behavior |
|---|---|
| `retry_fallback_on` | retry with next `voice_preferences` entry |
| `surface_to_user` | show the user a banner; do not retry silently |
| `silent_ignore` | swallow (e.g. `canceled` when user hit Stop) |

## ⟶ NEXT rules of thumb

- After `translate_and_speak`: ⟶ NEXT is usually "play the utterance, then
  call `validate_word` on any OOV/coverage-<1 token."
- After `validate_word` returns `verified`: ⟶ NEXT is "run
  `build.api.rebuild_with_extensions` to ship the new record."
- After `validate_word` returns `pending_audit`: ⟶ NEXT is "collect a human
  verdict via `audit_submit`."

⟶ NEXT: [API_REFERENCE.md](API_REFERENCE.md) — formal spec.
