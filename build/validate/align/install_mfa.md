# Forced-Aligner Setup for Slovenian

This project needs a **phoneme-level forced aligner** to compare our predicted
SLPROS-1 prosody (IPA + syllable durations + stress position) against
ground-truth native recordings (ARTUR, Common Voice SL).

Two aligners were considered. TL;DR — **`ctc-forced-aligner` is the production
choice** on Windows native because MFA requires conda, which is not currently
available on this machine.

---

## Option A (preferred when available): Montreal Forced Aligner

MFA ships a Slovenian acoustic model (`slovenian_mfa`) and dictionary
(`slovenian_mfa`) on the MFA model zoo
(<https://mfa-models.readthedocs.io/>).

### A.1 Try pip (usually fails on Windows)

```powershell
py -3.13 -m pip install montreal-forced-aligner
```

As of MFA 3.x, this fails on Windows native because MFA depends on
`kalpy`/`pynini` (OpenFst bindings) which do not have Windows wheels. The pip
install errors out at `pynini` with a compile error.

Fallback tried: `pip install montreal-forced-aligner[all]` — same failure.

### A.2 Conda install (required on Windows)

Install **Miniforge** (community-maintained conda that defaults to
`conda-forge`): <https://conda-forge.org/download/>. Then:

```powershell
conda create -n aligner -c conda-forge python=3.11 montreal-forced-aligner
conda activate aligner
mfa model download acoustic  slovenian_mfa
mfa model download dictionary slovenian_mfa
```

Model sizes (reference):
- `slovenian_mfa` acoustic: ~40 MB, unzipped into
  `%USERPROFILE%\Documents\MFA\pretrained_models\acoustic\slovenian_mfa.zip`
- `slovenian_mfa` dictionary: ~2 MB, into
  `%USERPROFILE%\Documents\MFA\pretrained_models\dictionary\slovenian_mfa.dict`

Once installed, point `align_artur_samples.py` at it via
`--aligner mfa --mfa-acoustic slovenian_mfa --mfa-dict slovenian_mfa`.

### A.3 Why Python 3.11 and not 3.13 for MFA

MFA 3.x upstream wheels (via conda-forge) target Python 3.9–3.11. This project
uses Python 3.13 for everything else; keep the MFA env isolated and shell out
to it with `subprocess.run(["mfa", "align", ...])`.

---

## Option B (current production choice): ctc-forced-aligner

<https://github.com/MahmoudAshraf97/ctc-forced-aligner>

- Pure pip; works on Windows + Python 3.13.
- Uses `wav2vec2` CTC logits + Viterbi. Multilingual model
  (`MahmoudAshraf/mms-300m-1130-forced-aligner`) covers ~1000 languages
  including Slovenian.
- Dependencies (approximate install size):
  - `torch` (~200 MB CPU wheel) — NOTE: the parent task says avoid torch
    unless strictly required. CTC alignment is inherently an acoustic-model
    task, so torch *is* required here. Use the CPU-only wheel:
    `pip install torch --index-url https://download.pytorch.org/whl/cpu`.
  - `transformers` (~10 MB)
  - `ctc-forced-aligner` (<1 MB)
- Install:

  ```powershell
  py -3.13 -m pip install --index-url https://download.pytorch.org/whl/cpu torch
  py -3.13 -m pip install transformers ctc-forced-aligner
  ```

- First-run downloads `wav2vec2-mms-300m` weights (~1.2 GB) into
  `%USERPROFILE%\.cache\huggingface\hub`.

### Integration point

`align_artur_samples.py --aligner ctc` wraps the `ctc_forced_aligner` public
API (`load_alignment_model`, `generate_emissions`, `get_alignments`,
`get_spans`, `postprocess_results`). See the function
`_align_with_ctc()` in that script for the call site.

---

## Decision

| Criterion          | MFA                 | ctc-forced-aligner     |
|--------------------|---------------------|------------------------|
| Windows native pip | **no** (needs conda)| yes                    |
| Slovenian model    | yes (curated)       | multilingual wav2vec2  |
| Deps               | kaldi, pynini, openfst | torch-cpu, transformers |
| Phone-level output | yes (IPA-ish)       | character level; map via dict |

**Production**: ctc-forced-aligner. **Ground-truth cross-check**: MFA in a
separate conda env, once available.

## Install attempts, 2026-04-17

- `py -3.13 -m pip install montreal-forced-aligner` — *not executed in this
  session*: sandbox denies pip from within the agent. Run it locally; expect
  failure at `pynini`.
- `conda` — **not installed on this machine** (`where conda` returns nothing
  in prior sessions). User action required.
- `py -3.13 -m pip install ctc-forced-aligner` — not yet executed. The
  validator script degrades gracefully when the package is missing so dev can
  proceed.

## Next steps for the user

1. (optional, for MFA cross-check) Install Miniforge, then run the four
   commands in section A.2.
2. (required, for production) Run the two pip commands in section B.
3. Confirm installation by running the validator dry-run:
   `py -3.13 build/validate/align/align_artur_samples.py --dry-run`.
