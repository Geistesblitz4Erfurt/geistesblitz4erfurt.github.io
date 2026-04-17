"""Character-level CTC forced alignment for Slovenian speech corpora.

We load :mod:`anton-l/wav2vec2-large-xlsr-53-slovenian` (XLSR-53 fine-tuned on
Common Voice SL, CC-BY-4.0). The model is character-CTC with a 31-symbol vocab
covering the Slovene alphabet + ``|`` (word boundary) + ``[PAD]`` (CTC blank).

Given a clip + its ground-truth transcript we:

    1. resample to 16 kHz mono and run the model to get emission log-probs
       of shape ``(T_frames, V=31)``;
    2. construct the CTC label sequence by mapping each character of the
       transcript to its vocab id (unknown → ``[UNK]``);
    3. run a standard CTC forced-alignment Viterbi to get the most likely
       alignment path over frames;
    4. collapse consecutive identical labels into character spans
       ``(char, t_start, t_end, score)`` — expressed in seconds.

Additionally we extract an F0 contour via YIN and attach per-character
mean-F0 + duration so downstream prosody learning can build conditional
probability tables on top.

Output per clip: a JSON record with::

    {
      "clip": "path/to/clip.mp3",
      "text": "...",
      "duration_s": 3.14,
      "sample_rate": 16000,
      "chars": [{"ch":"k","t0":0.12,"t1":0.19,"f0_mean_hz":180.5,"score":-2.3}, ...],
      "f0_stats": {"mean_hz": ..., "median_hz": ..., "baseline_hz": ...}
    }

We deliberately do *not* do phoneme-level alignment here. Slovenian orthography
is phonemically close enough that character-level alignment maps onto IPA
downstream via the Sloleks IPA sequence (``word_form.ipa``). That re-mapping
happens in :mod:`build.prosody.cpt_learner`, not here.

Run::

    PYTHONIOENCODING=utf-8 python -m build.align.ctc_align --smoke

Smoke mode aligns 5 clips from ``sources/common_voice/17.0/clips`` and prints
results. For full batch use::

    python -m build.align.ctc_align --manifest sources/udsst_audio/manifest.tsv \
        --limit 500 --out build/_udsst_aligned.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO_ROOT / "sources" / "wav2vec2_sl"

_TORCH = None
_MODEL = None
_PROCESSOR = None
_DEVICE = "cpu"
_DTYPE = None  # set after torch imports
_VOCAB_ID: dict[str, int] = {}
_ID_VOCAB: dict[int, str] = {}
_BLANK_ID = 0


def _lazy_model(device: str = "auto"):
    """Load wav2vec2 onto the requested device. ``device='auto'`` picks cuda if available.

    On GPU we also cast to fp16 — the emission log-probs are then fp32 via a final
    log-softmax in fp32 to avoid saturating large negative exponents.
    """
    global _TORCH, _MODEL, _PROCESSOR, _DEVICE, _DTYPE, _VOCAB_ID, _ID_VOCAB, _BLANK_ID
    if _MODEL is not None:
        return _TORCH, _MODEL, _PROCESSOR
    import torch  # type: ignore
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor  # type: ignore

    _TORCH = torch
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    _DEVICE = device
    _DTYPE = torch.float16 if device == "cuda" else torch.float32

    _PROCESSOR = Wav2Vec2Processor.from_pretrained(str(MODEL_DIR))
    _MODEL = Wav2Vec2ForCTC.from_pretrained(str(MODEL_DIR))
    _MODEL.eval()
    _MODEL.to(device=device, dtype=_DTYPE)

    vocab = _PROCESSOR.tokenizer.get_vocab()
    _VOCAB_ID = dict(vocab)
    _ID_VOCAB = {v: k for k, v in vocab.items()}
    _BLANK_ID = _VOCAB_ID.get("[PAD]", 0)
    print(f"[align] model loaded on device={_DEVICE} dtype={_DTYPE}", flush=True)
    return _TORCH, _MODEL, _PROCESSOR


def _load_audio(path: Path, target_sr: int = 16000) -> np.ndarray:
    import soundfile as sf  # type: ignore
    import librosa  # type: ignore

    data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if data.ndim == 2:
        data = data.mean(axis=1)
    if sr != target_sr:
        data = librosa.resample(data, orig_sr=sr, target_sr=target_sr)
    # peak normalize to avoid clipping during emission
    peak = float(np.max(np.abs(data))) or 1.0
    if peak > 0:
        data = data / peak
    return data.astype(np.float32)


def _encode_transcript(text: str) -> list[int]:
    """Map orthographic text to CTC label ids. Unknown → [UNK]."""
    ids: list[int] = []
    unk = _VOCAB_ID.get("[UNK]", 0)
    pipe = _VOCAB_ID.get("|", 0)
    prev_space = True
    for ch in text.lower():
        if ch.isspace():
            if not prev_space:
                ids.append(pipe)
                prev_space = True
            continue
        if ch in _VOCAB_ID:
            ids.append(_VOCAB_ID[ch])
        else:
            # skip unknown punctuation entirely rather than inject [UNK]
            continue
        prev_space = False
    return ids


def _ctc_forced_align(emissions: np.ndarray, labels: list[int]) -> list[int]:
    """Viterbi CTC forced alignment.

    emissions: (T, V) log-probabilities
    labels: target token id sequence (no blanks)
    returns: per-frame label id (may include blank)

    Standard CTC state expansion: interleave blanks, allow self/next/skip
    transitions. Implementation is ``O(T*(2L+1))`` on log-probabilities.
    """
    T, V = emissions.shape
    blank = _BLANK_ID
    # extended labels: blank, y1, blank, y2, ..., blank
    ext = [blank]
    for y in labels:
        ext.append(y)
        ext.append(blank)
    S = len(ext)

    NEG_INF = -1e30
    trellis = np.full((T, S), NEG_INF, dtype=np.float64)
    backpointer = np.zeros((T, S), dtype=np.int8)

    trellis[0, 0] = emissions[0, ext[0]]
    if S >= 2:
        trellis[0, 1] = emissions[0, ext[1]]

    for t in range(1, T):
        em = emissions[t]
        # same state
        s0 = trellis[t - 1]
        # previous state
        s1 = np.concatenate(([NEG_INF], trellis[t - 1, :-1]))
        # skip previous (only valid when ext[s] != ext[s-2] and ext[s] != blank)
        s2 = np.full(S, NEG_INF)
        for s in range(2, S):
            if ext[s] != blank and ext[s] != ext[s - 2]:
                s2[s] = trellis[t - 1, s - 2]
        stacked = np.stack([s0, s1, s2], axis=0)
        best = stacked.argmax(axis=0)
        maxv = stacked.max(axis=0)
        trellis[t] = maxv + em[ext]
        backpointer[t] = best

    # backtrack from the better of the last two states
    last = S - 1 if trellis[T - 1, S - 1] >= trellis[T - 1, S - 2] else S - 2
    path = [0] * T
    s = last
    for t in range(T - 1, -1, -1):
        path[t] = ext[s]
        if t == 0:
            break
        step = int(backpointer[t, s])
        if step == 1:
            s -= 1
        elif step == 2:
            s -= 2
    return path


def _path_to_spans(path: list[int], frame_s: float) -> list[dict]:
    """Collapse per-frame labels into character spans, dropping blanks."""
    spans: list[dict] = []
    prev = None
    t0 = 0
    for t, lab in enumerate(path):
        if lab != prev:
            if prev is not None and prev != _BLANK_ID:
                ch = _ID_VOCAB.get(prev, "?")
                if ch not in ("[PAD]", "[UNK]"):
                    spans.append(
                        {
                            "ch": ch,
                            "t0": round(t0 * frame_s, 4),
                            "t1": round(t * frame_s, 4),
                        }
                    )
            t0 = t
            prev = lab
    if prev is not None and prev != _BLANK_ID:
        ch = _ID_VOCAB.get(prev, "?")
        if ch not in ("[PAD]", "[UNK]"):
            spans.append(
                {
                    "ch": ch,
                    "t0": round(t0 * frame_s, 4),
                    "t1": round(len(path) * frame_s, 4),
                }
            )
    return spans


def _f0_contour(audio: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (times_s, f0_hz) via YIN. Unvoiced frames are NaN."""
    import librosa  # type: ignore

    f0, voiced, _ = librosa.pyin(
        audio,
        fmin=80.0,
        fmax=500.0,
        sr=sr,
        frame_length=2048,
        hop_length=256,
    )
    times = librosa.times_like(f0, sr=sr, hop_length=256)
    return times, f0


def _attach_f0(spans: list[dict], times: np.ndarray, f0: np.ndarray) -> None:
    for sp in spans:
        t0, t1 = sp["t0"], sp["t1"]
        mask = (times >= t0) & (times < t1)
        if not mask.any():
            sp["f0_mean_hz"] = None
            continue
        vals = f0[mask]
        vals = vals[np.isfinite(vals)]
        sp["f0_mean_hz"] = round(float(vals.mean()), 2) if vals.size else None


def align_one(audio_path: Path, text: str) -> dict:
    torch, model, _ = _lazy_model()
    audio = _load_audio(audio_path)
    with torch.inference_mode():
        inputs = _PROCESSOR(audio, sampling_rate=16000, return_tensors="pt")
        input_values = inputs["input_values"].to(device=_DEVICE, dtype=_DTYPE)
        logits = model(input_values).logits.squeeze(0)
        # upcast to fp32 before log-softmax
        log_probs_t = torch.log_softmax(logits.float(), dim=-1)
        log_probs = log_probs_t.cpu().numpy()
    T = log_probs.shape[0]
    duration_s = len(audio) / 16000.0
    frame_s = duration_s / T

    labels = _encode_transcript(text)
    if not labels:
        return {
            "clip": str(audio_path),
            "text": text,
            "duration_s": round(duration_s, 3),
            "sample_rate": 16000,
            "error": "empty label sequence",
            "chars": [],
        }
    # CTC requires T >= 2L+1
    if T < 2 * len(labels) + 1:
        return {
            "clip": str(audio_path),
            "text": text,
            "duration_s": round(duration_s, 3),
            "sample_rate": 16000,
            "error": f"audio too short for transcript ({T} frames, need {2*len(labels)+1})",
            "chars": [],
        }

    path = _ctc_forced_align(log_probs, labels)
    spans = _path_to_spans(path, frame_s)

    times, f0 = _f0_contour(audio, 16000)
    _attach_f0(spans, times, f0)

    finite = f0[np.isfinite(f0)]
    stats = {
        "mean_hz": round(float(finite.mean()), 2) if finite.size else None,
        "median_hz": round(float(np.median(finite)), 2) if finite.size else None,
        "baseline_hz": round(float(np.percentile(finite, 10)), 2) if finite.size else None,
    }
    return {
        "clip": str(audio_path),
        "text": text,
        "duration_s": round(duration_s, 3),
        "sample_rate": 16000,
        "chars": spans,
        "f0_stats": stats,
    }


def _batched_forward(audios: list[np.ndarray]) -> list[np.ndarray]:
    """Batch wav2vec2 forward over clips, return per-clip log-probs (fp32 numpy).

    Pads the batch to the longest clip. Per-clip T_out is clipped to
    ``ceil(T_in_true / 320)`` (the model's 50 Hz hop) so padding frames don't
    leak into the emission matrix.
    """
    torch, model, _ = _lazy_model()
    if not audios:
        return []
    lens = [a.shape[0] for a in audios]
    T_in_max = max(lens)
    batch = np.zeros((len(audios), T_in_max), dtype=np.float32)
    for i, a in enumerate(audios):
        batch[i, : a.shape[0]] = a
    attn = np.zeros((len(audios), T_in_max), dtype=np.int64)
    for i, L in enumerate(lens):
        attn[i, :L] = 1
    with torch.inference_mode():
        t_in = torch.from_numpy(batch).to(device=_DEVICE, dtype=_DTYPE)
        t_attn = torch.from_numpy(attn).to(device=_DEVICE)
        logits = model(t_in, attention_mask=t_attn).logits
        log_probs = torch.log_softmax(logits.float(), dim=-1).cpu().numpy()
    # model downsamples ~320×; compute valid output frames per sample
    out = []
    T_out = log_probs.shape[1]
    for i, L in enumerate(lens):
        T_valid = min(T_out, max(1, L // 320))
        out.append(log_probs[i, :T_valid, :])
    return out


def _postprocess_one(audio_path: Path, text: str, audio: np.ndarray, log_probs: np.ndarray) -> dict:
    """CPU-bound per-clip post-processing: Viterbi + F0 + F0 attachment."""
    T = log_probs.shape[0]
    duration_s = len(audio) / 16000.0
    frame_s = duration_s / max(T, 1)
    labels = _encode_transcript(text)
    if not labels:
        return {"clip": str(audio_path), "text": text, "duration_s": round(duration_s, 3), "sample_rate": 16000, "error": "empty label sequence", "chars": []}
    if T < 2 * len(labels) + 1:
        return {"clip": str(audio_path), "text": text, "duration_s": round(duration_s, 3), "sample_rate": 16000, "error": f"audio too short for transcript ({T} frames, need {2*len(labels)+1})", "chars": []}
    path = _ctc_forced_align(log_probs, labels)
    spans = _path_to_spans(path, frame_s)
    times, f0 = _f0_contour(audio, 16000)
    _attach_f0(spans, times, f0)
    finite = f0[np.isfinite(f0)]
    stats = {
        "mean_hz": round(float(finite.mean()), 2) if finite.size else None,
        "median_hz": round(float(np.median(finite)), 2) if finite.size else None,
        "baseline_hz": round(float(np.percentile(finite, 10)), 2) if finite.size else None,
    }
    return {
        "clip": str(audio_path),
        "text": text,
        "duration_s": round(duration_s, 3),
        "sample_rate": 16000,
        "chars": spans,
        "f0_stats": stats,
    }


def align_batch(items: list[tuple[Path, str]], n_cpu_workers: int = 0) -> list[dict]:
    """Align a batch of ``(audio_path, text)`` pairs.

    Stage 1 (GPU-saturated): one forward pass for the whole batch.
    Stage 2 (CPU per-clip): Viterbi + F0 + F0 attachment, optionally parallel.

    ``n_cpu_workers=0`` → serial post-process. When the GPU is fast enough that
    F0/Viterbi dominates wall time, set this to 4–8 to run librosa.pyin + the
    numpy Viterbi in a ThreadPoolExecutor (both release the GIL via numpy/scipy).
    """
    _lazy_model()
    # Audio load is also CPU+IO bound — parallelise if a pool is requested.
    audios: list[np.ndarray] = []
    if n_cpu_workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=n_cpu_workers) as ex:
            audios = list(ex.map(_load_audio, [p for p, _ in items]))
    else:
        audios = [_load_audio(p) for p, _ in items]

    log_probs_list = _batched_forward(audios)

    if n_cpu_workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=n_cpu_workers) as ex:
            results = list(ex.map(
                lambda args: _postprocess_one(*args),
                [((p, t, a, lp)) for (p, t), a, lp in zip(items, audios, log_probs_list)],
            ))
        return results
    return [_postprocess_one(p, t, a, lp) for (p, t), a, lp in zip(items, audios, log_probs_list)]


def _iter_udsst_manifest(manifest_path: Path):
    with manifest_path.open("r", encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for ln in fh:
            parts = ln.rstrip("\n").split("\t")
            if len(parts) < len(header):
                continue
            row = dict(zip(header, parts))
            yield row


def _iter_cv_manifest(manifest_path: Path):
    with manifest_path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            yield row


def _batch_align(
    manifest_path: Path,
    clips_root: Path,
    limit: int,
    out: Path,
    is_cv: bool,
    batch_size: int = 1,
) -> int:
    """Stream clips from the manifest; flush in batches of ``batch_size``.

    Length-sort within each micro-batch so padding waste is bounded.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    ok = 0
    t_start = time.time()
    buf: list[tuple[Path, str]] = []

    def flush(fh) -> tuple[int, int]:
        nonlocal buf
        if not buf:
            return 0, 0
        # length-sort by rough audio size to minimise padding inside the batch
        buf.sort(key=lambda it: it[0].stat().st_size if it[0].exists() else 0)
        try:
            recs = align_batch(buf) if batch_size > 1 else [align_one(p, t) for p, t in buf]
        except Exception as exc:
            recs = [{"clip": str(p), "text": t, "error": f"{type(exc).__name__}: {exc}"} for p, t in buf]
        dn = len(recs)
        dok = 0
        for rec in recs:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if rec.get("chars"):
                dok += 1
        buf = []
        return dn, dok

    with out.open("w", encoding="utf-8") as fh:
        iterator = _iter_cv_manifest(manifest_path) if is_cv else _iter_udsst_manifest(manifest_path)
        for row in iterator:
            if limit and n >= limit:
                break
            if is_cv:
                clip_name = row.get("path", "")
                if not clip_name:
                    continue
                clip_path = clips_root / clip_name
                text = row.get("sentence", "")
            else:
                clip_path = REPO_ROOT / row.get("local_path", "")
                text = row.get("text", "")
            if not clip_path.exists() or not text.strip():
                continue
            n += 1
            buf.append((clip_path, text))
            if len(buf) >= batch_size:
                _, dok = flush(fh)
                ok += dok
                if n % max(20, batch_size) < batch_size:
                    dt = time.time() - t_start
                    rate = n / max(dt, 0.001)
                    print(f"[align] n={n} ok={ok} {rate:.2f} clips/s elapsed={dt:.0f}s", flush=True)
        _, dok = flush(fh)
        ok += dok
    print(f"[align] DONE n={n} ok={ok} out={out}")
    return ok


def _smoke() -> int:
    cv_clips = REPO_ROOT / "sources" / "common_voice" / "17.0" / "clips"
    manifest = REPO_ROOT / "sources" / "common_voice" / "17.0" / "manifest.tsv"
    rows = list(_iter_cv_manifest(manifest))
    rows = [r for r in rows if (cv_clips / r["path"]).exists()][:5]
    for row in rows:
        rec = align_one(cv_clips / row["path"], row["sentence"])
        summary = {
            "clip": Path(rec["clip"]).name,
            "text": (row["sentence"][:60] + "…") if len(row["sentence"]) > 60 else row["sentence"],
            "duration_s": rec.get("duration_s"),
            "n_chars": len(rec.get("chars", [])),
            "f0_mean": (rec.get("f0_stats") or {}).get("mean_hz"),
            "error": rec.get("error"),
        }
        print(json.dumps(summary, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="align 5 CV clips")
    ap.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="TSV manifest (UD-SST or CV format, auto-detected by header)",
    )
    ap.add_argument("--clips-root", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=0, help="cap at N clips (0 = all)")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "build" / "_aligned.jsonl")
    ap.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cuda", "cpu"],
        help="wav2vec2 compute device",
    )
    ap.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="GPU batch size (0 = auto: 8 on cuda, 1 on cpu)",
    )
    args = ap.parse_args()
    _lazy_model(args.device)
    bs = args.batch_size
    if bs <= 0:
        bs = 8 if _DEVICE == "cuda" else 1

    if args.smoke:
        return _smoke()

    if not args.manifest:
        ap.error("provide --manifest or --smoke")
    is_cv = "path" in args.manifest.read_text(encoding="utf-8").splitlines()[0].split("\t")
    if args.clips_root is None:
        args.clips_root = (
            REPO_ROOT / "sources" / "common_voice" / "17.0" / "clips"
            if is_cv
            else REPO_ROOT
        )
    _batch_align(args.manifest, args.clips_root, args.limit, args.out, is_cv, batch_size=bs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
