# SL-Pron — Native Slovenian Speech (offline-installable)

Deterministic, scientifically validated Slovenian pronunciation engine. Ships
as a static GitHub Pages site + installable **Voice-Pack PWA** (download once,
speak offline).

**Live site:** https://geistesblitz4erfurt.github.io/
**Install Voice-Pack:** https://geistesblitz4erfurt.github.io/install.html

## What's in here

| Area | Path |
|---|---|
| Phrasebook API (477 records, 63 kB gz) | [data/api/phrasebook.json.gz](data/api/phrasebook.json.gz) |
| Voice-Pack manifest (211 assets, 20.7 MB) | [data/api/voicepack/manifest.json](data/api/voicepack/manifest.json) |
| Per-word audio samples (Lingua-Libre CC-BY-SA) | [data/audio/words/](data/audio/words/) |
| Web test UI + PWA | [web_test/](web_test/) |
| Install page + service worker | [web_test/install.html](web_test/install.html), [web_test/sw.js](web_test/sw.js) |
| Build pipeline (Python) | [build/](build/) |
| Local test server | [serve/test_server.py](serve/test_server.py) |
| MCP server (Claude Desktop / Agent SDK) | [mcp_server/sl_pron_mcp.py](mcp_server/sl_pron_mcp.py) |
| Test suite (3431 tests) | [tests/python/](tests/python/) |
| Docs | [docs/](docs/) |

## Guarantees

- **477/477** records pass 10 corpus-level guarantees (G1-G10)
- **3431/3431** pytest tests green
- Every Voice-Pack asset has sha1 + size verified client-side on install
- Manifest schema: `slpron-voicepack.v1`, `lang: sl-SI`, `license: CC-BY-SA-4.0`
- W3C Web-App-Manifest with `web+slpron:` protocol handler

## License

CC-BY-SA 4.0 (inherited from Sloleks 3.1). Attribution: CJVT University of
Ljubljana, Lingua Libre / Wikimedia Commons. Full notice:
[data/api/LICENSE_ATTRIBUTION.md](data/api/LICENSE_ATTRIBUTION.md).

## Quick start (local)

```bash
python -m build.api.build_voicepack -v
python -m serve.test_server
# open http://127.0.0.1:8765/install.html
```

See [docs/INSTALL_GUIDE.md](docs/INSTALL_GUIDE.md), [docs/HUMAN_GUIDE.md](docs/HUMAN_GUIDE.md),
[docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md), [docs/API_REFERENCE.md](docs/API_REFERENCE.md),
[docs/DEPLOY_GUIDE.md](docs/DEPLOY_GUIDE.md).
