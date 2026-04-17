# SL-Pron — Deploy Guide

## 1. GitHub Pages (static)

The shipped API is just gzipped JSON. GitHub Pages serves it natively.

### What gets deployed

```
gh-pages/
├── index.html            # verbatim copy of web_test/index.html, minus server-only UI
├── data/
│   └── api/
│       ├── phrasebook.json.gz
│       ├── phrasebook_index.json
│       ├── LICENSE_ATTRIBUTION.md
│       ├── proof_report.json
│       ├── deep_validation_report.json
│       └── verified_words.json
```

### Workflow

Triggers on `push` to `main` that touches `data/api/**`, `web_test/**`, or
`docs/**`. See `.github/workflows/deploy.yml`.

```yaml
name: Deploy to GitHub Pages
on:
  push:
    branches: [main]
    paths: ["data/api/**", "web_test/**", "docs/**"]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - name: Stage gh-pages payload
        run: |
          mkdir -p gh-pages/data/api
          cp web_test/index.html gh-pages/index.html
          cp data/api/phrasebook.json.gz       gh-pages/data/api/
          cp data/api/phrasebook_index.json    gh-pages/data/api/
          cp data/api/LICENSE_ATTRIBUTION.md   gh-pages/data/api/
          cp data/api/proof_report.json        gh-pages/data/api/  || true
          cp data/api/deep_validation_report.json gh-pages/data/api/ || true
          cp data/api/verified_words.json      gh-pages/data/api/   || true
          cp data/api/evidence_dashboard.json  gh-pages/data/api/   || true
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: gh-pages/
      - id: deployment
        uses: actions/deploy-pages@v4
```

### Client-side degradation

Pages has no Python runtime, so `/api/synthesize` is unavailable. The
deployed `index.html` detects a `?static=1` or server-404 and switches to
client-only mode: it reads `phrasebook.json.gz` directly and only answers
phrases present there. Live synthesis shows a banner pointing at the local
server instructions.

## 2. Optional dynamic backend

If you want the live pipeline online, wrap `serve/test_server.py` with
FastAPI and deploy on Fly.io / Render / any Python host. Two invariants:

1. CORS must explicitly allow `https://<your>.github.io`.
2. `PYTHONIOENCODING=utf-8` must be set — Windows build boxes silently
   corrupt `č/š/ž` under `cp1252`.

## 3. Claude Desktop MCP registration

Copy `mcp_server/manifest.json.claude_desktop_config_snippet` into your
Claude Desktop config:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "sl-pron": {
      "command": "python",
      "args": ["-m", "mcp_server.sl_pron_mcp"],
      "cwd": "C:/Users/Jaman/PycharmProjects/slovenisch_deutsch",
      "env": {"PYTHONIOENCODING": "utf-8"}
    }
  }
}
```

Restart Claude Desktop. The five tools show up under the plugin drawer.

## 4. Claude Agent SDK

Same manifest; load via the SDK's MCP client. The ⟶ NEXT convention means
the tool results chain deterministically — the agent can call
`translate_and_speak` → `validate_word` → `rebuild_with_extensions` without
additional prompting.

## 5. Release ritual (maintainer)

```bash
# 1. integrate new verified words
python -m build.api.rebuild_with_extensions

# 2. reprove the corpus
python -m build.validate.api_corpus_proof
python -m build.validate.deep_validate

# 3. run unit + directive tests
pytest tests/python/

# 4. smoke the server
python -m serve.test_server &
curl -s http://127.0.0.1:8765/api/health

# 5. commit data/api/* + push → GH Action deploys to Pages
git add data/api/ docs/
git commit -m "release: SLPROS-1 x.y.z"
git push
```

⟶ NEXT: confirm the CI run, then link the live Pages URL in the repo README.
