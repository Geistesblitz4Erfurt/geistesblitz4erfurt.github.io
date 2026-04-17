# SL-Pron — Human Guide

A 5-minute tour of the test page and the audit workflow.

## 1. Install a Slovenian voice

Your browser's `SpeechSynthesisVoice` catalogue determines whether SL-Pron
can speak Slovenian natively. SL-Pron refuses to fall back to English/German
voices — a missing SL voice surfaces as a visible error.

### Windows 10 / 11 — Microsoft Lado

1. Settings → Time & Language → Language & Region.
2. Add a language → "Slovenščina" → install.
3. In the language tile: Options → Speech → install the *Speech* package.
4. Restart your browser. A `sl-SI · Microsoft Lado` entry appears in the
   "Available voices" card.

### Android / Chrome

Google's Slovenian voice ships with the Speech-Services app. If the voice
card shows "No Slovenian voice installed", open the Play Store, search
"Google Speech Services", and install the Slovenian language pack from
Settings → System → Languages → TTS output.

### Linux — eSpeak-NG fallback

`sudo apt install espeak-ng speech-dispatcher-espeak`. The voice shows as
`sl` (not `sl-SI`); quality is mechanical but linguistically correct.

## 2. The test page

Start the local server:

```
python -m serve.test_server
```

Open `http://127.0.0.1:8765/`.

### Top card — speak an English sentence

- Type English. Press Enter or click **Speak**.
- The server either returns a **phrasebook** record (O(1), 477 shipped
  records) or runs the **live pipeline** (translate + IPA + SLPROS-1).
- The SL text, the joined IPA, and a per-token grid render immediately.

### Lookup / coverage / voice badges

- **lookup: phrasebook** (green) = exact hit.
- **lookup: live** (orange) = live translation — always followed by a coverage number.
- **coverage: 1.00** (green) = every token has real Sloleks IPA (not G2P-fallback).
- **voice: Microsoft Lado** etc. = the chosen SL voice.

### Audit panel

After each speak:

- ✓ **Native-quality**: output is indistinguishable from a Slovene.
- △ **Accent off**: correct words, non-native accent.
- ✗ **Wrong pronunciation**: audible phoneme errors.
- ✗ **Not Slovenian**: voice rendered Croatian/Polish/Russian.
- ✗ **Wrong translation**: words are mistranslated.
- ? **No SL voice installed**.

Every click writes to *both* `localStorage["slpron_audit_v1"]` (personal log)
and `POST /api/audit_submit` (server log → `data/api/audit_log.jsonl`).

### Verify-word form

Enter an EN gloss + an SL surface form. The server runs the deep L1–L6 pipeline:

| Layer | Check |
|---|---|
| L1 | Sloleks ships the word |
| L2 | `slovene_g2p` IPA matches Sloleks within 1 edit |
| L3 | Syllable count matches |
| L4 | Audio duration (if any) ≈ n_syllables × 180 ms |
| L5 | wav2vec2 forced-alignment confidence (if audio present) |
| L6 | Back-translation `en → sl` survives the round trip |

**Score ≥ 0.90** → persisted to `verified_extensions.jsonl`.
**Score ∈ [0.70, 0.90)** → persisted to `pending_audit.jsonl` for human review.

### Live stats card

Auto-refreshes every 15 s. Shows shipped record count, verified extensions,
pending audits, and cumulative audit submissions.

## 3. Export / import the audit log

- **Export JSON** downloads the full `localStorage` log.
- **Clear** wipes *localStorage only* — server log remains.

## 4. Merging verified words into the next release

```
python -m build.api.rebuild_with_extensions
```

This rolls `verified_extensions.jsonl` into `phrasebook.json.gz`, bumps the
`pipeline_version`, and re-runs the 10 G1–G10 corpus-proof guarantees.

## 5. Troubleshooting

- **"No Slovenian voice on this device"** — install Lado (§1).
- **Audio but wrong language** — check `voice-badge`; if it says the chosen
  voice is not `sl-*`, your system has no SL voice and SL-Pron is refusing
  to fall back.
- **coverage < 1.0** — some token fell to G2P fallback; file a verify-word
  submission to promote that lemma into Sloleks-IPA-grade shipping.

⟶ NEXT: [AGENT_GUIDE.md](AGENT_GUIDE.md) — REST + MCP cookbooks.
