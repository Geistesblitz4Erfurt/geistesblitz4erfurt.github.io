# SL-Pron — Install Guide (PWA Voice-Pack)

This guide documents the **download-a-language**-style install flow: how a
browser picks up `/data/api/voicepack/manifest.json`, persists the bundle in
Cache Storage, and then speaks Slovenian offline — even if the OS ships no
`sl-SI` voice.

## 1. End-user flow

1. Open `https://<host>/install.html` (or `https://<host>/` → banner → click
   **Install Voice-Pack** if no native `sl-SI` voice is detected).
2. Browser fetches `/data/api/voicepack/manifest.json` (schema
   `slpron-voicepack.v1`).
3. `navigator.storage.persist()` is requested — prevents automatic eviction.
4. Every asset is fetched sequentially, its sha1 verified, and cached under
   `sl-pron-voicepack-<version>`.
5. An IndexedDB record stores install metadata
   (`installed_at`, `manifest_version`, `bundle_sha1`, `total_bytes`).
6. Done — the site works offline, `/api/synthesize` falls back to the cached
   phrasebook, and unknown phrases trigger `VoiceFallback` (Web Audio stitching
   of installed samples).

## 2. Protocol-handler link (one-click speak)

After install, these URLs open the app and speak the phrase:

```
web+slpron:Dobro jutro.
web+slpron:Hvala lepa!
```

Registered via `protocol_handlers` in `web_test/manifest.webmanifest`; the app
reads `?phrase=…` on load.

## 3. Fallstricke — every caveat handled

| # | Pitfall | Mitigation |
|---|---|---|
| 1 | Service Worker requires HTTPS (or `localhost`) | GH Pages is HTTPS ✓; local dev uses `http://127.0.0.1` which browsers whitelist |
| 2 | iOS Safari limits Cache Storage to ~50 MB without install prompt | Manifest sets `min_quota_mb: 32`; installer warns if `estimate().quota` is below |
| 3 | Storage eviction under pressure | `navigator.storage.persist()` + explicit persistence flag in IndexedDB record |
| 4 | OGG/Opus not decodable on some iOS versions | Manifest lists `.wav` + `.oga`/`.ogg` alternatives; `VoiceFallback` lets the browser pick a decodable one |
| 5 | `AudioBufferSourceNode.detune` missing on older Safari | `voice_fallback.js` wraps the assignment in try/catch |
| 6 | Silent fetch/cors failures leaving empty cache entries | Installer rejects non-200 responses **before** `cache.put()` |
| 7 | Mixed origins (e.g. proxy) breaking Cache-Storage | All manifest URLs are site-root-relative; no absolute origins |
| 8 | Browser ships no `sl-SI` voice (Windows narrator, iOS Safari default) | `voice_fallback.js` concatenates installed samples; install banner surfaces the state |
| 9 | SHA-1 unavailable in `crypto.subtle` (legacy Edge) | Installer treats missing digest as non-fatal, trusts TLS for integrity |
| 10 | Protocol handler registration requires user gesture | Handler is declared in manifest — browsers prompt on first use, never via JS |
| 11 | Cache invalidation on manifest update | Cache name is `sl-pron-voicepack-<version>` — old caches stay until explicitly evicted via `EVICT_PACK` message |
| 12 | `DecompressionStream` missing on pre-2023 Safari | GH-Pages shim degrades to no-gzip phrasebook if absent; manifest still usable |
| 13 | Range requests on GH Pages | Pages serves `Accept-Ranges: bytes` for static files; installer doesn't depend on ranges |
| 14 | CORS on cross-origin install via Pages + custom API backend | Optional backend must set `Access-Control-Allow-Origin: https://<user>.github.io` |
| 15 | File:// origin breaks SW | Test only via `python -m http.server` or the bundled `serve/test_server.py` |

## 4. API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /data/api/voicepack/manifest.json` | Canonical manifest |
| `GET /api/voicepack/manifest.json` | Alias (redirect-friendly, served by `serve/test_server.py`) |
| `GET /api/voicepack/ping` | Lightweight status probe: `{ok, version, lang, license, bundle_sha1}` |
| `GET /data/audio/words/*` | Per-word samples (`.wav`/`.ogg`/`.oga`) |
| `GET /data/api/phrasebook.json.gz` | Main phrasebook |
| `GET /data/api/phrasebook_index.json` | English → record-id |
| `GET /data/api/voicepack/ipa_index.json.gz` | Surface → IPA fallback index |

## 5. Tests

Three pytest suites guard the install path:

```
tests/python/test_voicepack_manifest.py      # 14 tests — sha1/size/schema invariants
tests/python/test_web_manifest.py            #  9 tests — W3C Web App Manifest
tests/python/test_service_worker_syntax.py   #  7 tests — sw.js + install.js contract
```

Run them with:

```
python -m pytest tests/python/test_voicepack_manifest.py \
                 tests/python/test_web_manifest.py \
                 tests/python/test_service_worker_syntax.py -q
```

## 6. Rebuilding the pack

```
python -m build.api.build_voicepack -v
```

Produces `data/api/voicepack/manifest.json` + `ipa_index.json.gz`. Commit and
push — the `deploy.yml` workflow publishes the updated pack to GitHub Pages.

⟶ NEXT: run the full evidence chain with
`python -m build.validate.evidence_dashboard` and open
`data/api/evidence_dashboard.json` to confirm the pack is in sync with the
verified phrasebook.
