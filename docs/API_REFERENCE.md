# SL-Pron — API Reference

Pipeline version: **SLPROS-1** · spec: W3C Web Speech API · lang lock: **sl-SI**.

## REST (local test server)

Base: `http://127.0.0.1:8765`. All responses are `application/json;
charset=utf-8` with `Access-Control-Allow-Origin: *`.

### `GET /api/health`

```json
{"ok": true, "phrasebook_records": 477, "phrasebook_size_bytes": 64474}
```

### `GET /api/synthesize?en=<text>`

Phrasebook fast-path or live pipeline. Response schema:

```ts
interface SynthesizeResponse {
  lookup: "phrasebook" | "live";
  input_en: string;
  en_normalized: string;
  sl: string;
  contour_type: "decl" | "q_yn" | "q_wh" | "excl";
  coverage: number;                // 0..1
  tokens: Token[];
  slpros1: SLPROS1;                // per-syllable prosody
  speech_directive: SpeechDirective;
  category?: string;               // only in phrasebook hits
  id?: string;                     // only in phrasebook hits
}

interface Token {
  surface: string;
  ipa: string | null;              // post-sandhi
  ipa_pre_sandhi?: string;
  upos?: string;
  role?: string;
  source?: "sloleks" | "sloleks_case_fold" | "lemma_fallback" | "g2p" | ...;
  sandhi_notes: string[];          // "R1:prep_v_proclitic", "R5:enclitic", …
}

interface SpeechDirective {
  lang: "sl-SI";
  text: string;
  rate: number;                    // [0.1..10]
  pitch: number;                   // [0..2]
  volume: number;                  // [0..1]
  voice_preferences: string[];
  fallback: { never_fall_back_to_other_language: true; strategy: "concat_word_audio" };
  error_handling: {
    retry_fallback_on: string[];
    surface_to_user: string[];
    silent_ignore: string[];
  };
  boundary_hint: { expected_name_values: ("word" | "sentence")[] };
  spec_version: "W3C-WebSpeech";
  spec_url: string;
  events_consumed: string[];
  max_chunk_ms: 12000;
  total_predicted_duration_ms?: number;
}
```

### `GET /api/categories`

```json
{"count": 27, "categories": {"greetings": 31, ...}}
```

### `POST /api/validate_word`

Body:

```json
{"en": "house", "sl": "hiša", "ipa": "ˈxiːʃa"}
```

Response (abbreviated):

```json
{
  "ts": "2026-04-17T20:05:00Z",
  "en": "house",
  "sl": "hiša",
  "ipa": "ˈxiːʃa",
  "score": 0.95,
  "layer_results": {
    "L1": {"pass": true,  "conf": 1.00, "note": "ˈxiːʃa"},
    "L2": {"pass": true,  "conf": 1.00, "note": "lev=0 g2p=ˈxiːʃa"},
    "L3": {"pass": true,  "conf": 1.00, "note": "sloleks=2 heur=2"},
    "L4": {"pass": false, "conf": 0.00, "note": "no audio via API"},
    "L5": {"pass": false, "conf": 0.00, "note": "no audio via API"},
    "L6": {"pass": true,  "conf": 1.00, "note": "back=hiša"}
  },
  "persisted": "verified_extensions"
}
```

- `persisted == "verified_extensions"` iff score ≥ 0.90 and ≥3 layers passed.
- `persisted == "pending_audit"` iff 0.70 ≤ score < 0.90.
- `persisted == null` otherwise.

### `POST /api/audit_submit`

```json
{"id": "Good morning.|Dobro jutro.", "verdict": "ok", "note": "", "payload": {...}}
```

Writes to `data/api/audit_log.jsonl`.

### `GET /api/pending_audit?limit=100`

Paginated view (last-N) of `pending_audit.jsonl`.

### `GET /api/verified?since=<iso8601>`

Append-only feed of `verified_extensions.jsonl`.

### `GET /api/stats`

```json
{
  "shipped_records": 477,
  "verified_extensions": 0,
  "pending_audit": 0,
  "audit_submissions": 1,
  "avg_verified_score": 0.0
}
```

### `GET /data/api/phrasebook.json.gz`

Static artefact. `Content-Encoding: gzip`, `Content-Type: application/json`.
Browser decodes transparently. Shipped under CC-BY-SA 4.0.

## MCP (stdio transport)

Manifest: [mcp_server/manifest.json](../mcp_server/manifest.json).

Every tool response includes a `next` field with a free-text hint. Five tools:

1. `lookup_phrase(en)`
2. `translate_and_speak(en)`
3. `validate_word(en, sl, ipa="")`
4. `list_categories()`
5. `get_phonetic(sl)`

## Versioning policy

- `pipeline_version` is semantic: `major.minor.patch`.
- Record-shape changes bump **minor**.
- New records (extensions merged) bump **patch**.
- Breaking changes to `speech_directive` bump **major** — never without
  coordinated client release.

## Error codes (W3C SpeechSynthesisErrorCode)

Routed per `speech_directive.error_handling`:

| Code | Bucket | Why |
|---|---|---|
| `canceled` | silent_ignore | user hit Stop |
| `interrupted` | silent_ignore | new utterance superseded |
| `audio-busy` | retry_fallback_on | retry once |
| `audio-hardware` | surface_to_user | device issue |
| `network` | retry_fallback_on | remote voice flaked |
| `synthesis-unavailable` | surface_to_user | no engine |
| `synthesis-failed` | retry_fallback_on | retry with next voice |
| `language-unavailable` | surface_to_user | install SL voice |
| `voice-unavailable` | retry_fallback_on | next preference |
| `text-too-long` | surface_to_user | chunk to 12 000 ms |
| `invalid-argument` | surface_to_user | bug in caller |
| `not-allowed` | surface_to_user | user-gesture required |

⟶ NEXT: [DEPLOY_GUIDE.md](DEPLOY_GUIDE.md) — GH-Pages + MCP registration.
