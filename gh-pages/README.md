# gh-pages/ — deploy payload

**Do not edit files here directly.** The GitHub Action
[deploy.yml](../.github/workflows/deploy.yml) rebuilds this directory from
the canonical sources on every `push` to `main` that touches
`data/api/**`, `web_test/**`, `docs/**`, or `gh-pages/**`.

This directory is retained for local smoke-testing:

```
python -m http.server 8000 --directory gh-pages
open http://127.0.0.1:8000
```

The deployed page operates in **static mode**: it decompresses
`data/api/phrasebook.json.gz` client-side and serves `/api/synthesize` from
an in-memory lookup. Live synthesis (pipeline for unseen phrases) is not
available on GitHub Pages — run the local server for that.
