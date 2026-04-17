"""Local test server for the SL-Pron pipeline.

Runs a zero-dep stdlib HTTP server on http://127.0.0.1:8765 that exposes:

  GET  /                           -> web_test/index.html
  GET  /static/<path>              -> files under web_test/
  GET  /data/<path>                -> files under data/  (CORS-allowed)
  GET  /api/synthesize?en=<text>   -> run full EN->SL->SLPROS-1 pipeline
                                      (phrasebook fast-path + live fallback)
  GET  /api/health                 -> {"ok": true, "phrasebook_records": N}

The synthesize endpoint returns the same record shape as the static
phrasebook plus a ``lookup`` field marking ``"phrasebook"`` (exact O(1)
hit on the pre-built index) or ``"live"`` (real-time translate + synth).

Run::
    python -m serve.test_server
    python -m serve.test_server --port 9000 --host 0.0.0.0
"""
from __future__ import annotations

import argparse
import gzip
import json
import mimetypes
import re
import sys
import threading
import traceback
import unicodedata
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web_test"
PHRASEBOOK_GZ = DATA_DIR / "api" / "phrasebook.json.gz"
PHRASEBOOK_INDEX = DATA_DIR / "api" / "phrasebook_index.json"
VERIFIED_EXT = DATA_DIR / "api" / "verified_extensions.jsonl"
PENDING_AUDIT = DATA_DIR / "api" / "pending_audit.jsonl"
AUDIT_LOG = DATA_DIR / "api" / "audit_log.jsonl"

_APPEND_LOCK = threading.Lock()


def _append_jsonl(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False)
    with _APPEND_LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    return out

_NORMALIZE_RE = re.compile(r"[^\w\s]+", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_en(s: str) -> str:
    s = unicodedata.normalize("NFC", s).lower()
    s = _NORMALIZE_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


# --- Lazy, thread-safe Synthesizer -------------------------------------
_SYN_LOCK = threading.Lock()
_SYN = None  # type: ignore


def _synth():
    global _SYN
    if _SYN is None:
        with _SYN_LOCK:
            if _SYN is None:
                from build.pipeline.synthesize import Synthesizer
                _SYN = Synthesizer()
    return _SYN


@lru_cache(maxsize=1)
def _phrasebook() -> dict[str, dict]:
    if not PHRASEBOOK_GZ.exists():
        return {}
    records = json.loads(gzip.open(PHRASEBOOK_GZ, "rb").read())
    return {r["en_normalized"]: r for r in records}


@lru_cache(maxsize=1)
def _index() -> dict[str, str]:
    if not PHRASEBOOK_INDEX.exists():
        return {}
    return json.loads(PHRASEBOOK_INDEX.read_text(encoding="utf-8"))


# --- Directive emission (reuses build script logic) --------------------
def _directive_for(sl: str, slpros1: dict | None) -> dict:
    from build.api.build_phrasebook import _derive_speech_directive
    return _derive_speech_directive(sl, slpros1)


# --- HTTP handler ------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # less chatty
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    def _send_json(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, *, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404, "Not found")
            return
        if content_type is None:
            ctype, _ = mimetypes.guess_type(str(path))
            content_type = ctype or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        if path.suffix == ".gz":
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        ln = int(self.headers.get("Content-Length") or 0)
        if ln <= 0:
            return {}
        raw = self.rfile.read(ln)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def do_GET(self) -> None:  # noqa: N802 (stdlib contract)
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path == "/" or path == "/index.html":
                return self._send_file(WEB_DIR / "index.html")

            if path == "/api/health":
                return self._send_json(200, {
                    "ok": True,
                    "phrasebook_records": len(_phrasebook()),
                    "phrasebook_size_bytes": PHRASEBOOK_GZ.stat().st_size
                                              if PHRASEBOOK_GZ.exists() else 0,
                })

            if path == "/api/synthesize":
                en = (qs.get("en") or [""])[0].strip()
                if not en:
                    return self._send_json(400, {"error": "missing 'en' query param"})
                return self._handle_synthesize(en)

            if path == "/api/categories":
                pb = _phrasebook()
                cats: dict[str, int] = {}
                for r in pb.values():
                    c = r.get("category", "uncategorized")
                    cats[c] = cats.get(c, 0) + 1
                return self._send_json(200, {"count": len(cats), "categories": cats})

            if path == "/api/pending_audit":
                limit = int((qs.get("limit") or ["100"])[0])
                items = _read_jsonl(PENDING_AUDIT)[-limit:]
                return self._send_json(200, {"count": len(items), "items": items})

            if path == "/api/verified":
                since = (qs.get("since") or [""])[0]
                items = _read_jsonl(VERIFIED_EXT)
                if since:
                    items = [r for r in items if str(r.get("ts", "")) >= since]
                return self._send_json(200, {"count": len(items), "items": items})

            if path == "/install.html":
                return self._send_file(WEB_DIR / "install.html")

            if path == "/web_test/manifest.webmanifest":
                return self._send_file(WEB_DIR / "manifest.webmanifest")

            if path == "/web_test/sw.js":
                return self._send_file(WEB_DIR / "sw.js")

            if path == "/web_test/install.js":
                return self._send_file(WEB_DIR / "install.js")

            if path == "/web_test/voice_fallback.js":
                return self._send_file(WEB_DIR / "voice_fallback.js")

            if path == "/api/voicepack/manifest.json":
                mf = DATA_DIR / "api" / "voicepack" / "manifest.json"
                if not mf.exists():
                    return self._send_json(404, {"error": "voicepack not built — run `python -m build.api.build_voicepack`"})
                return self._send_file(mf)

            if path == "/api/voicepack/ping":
                mf = DATA_DIR / "api" / "voicepack" / "manifest.json"
                if not mf.exists():
                    return self._send_json(503, {"ok": False, "error": "manifest missing"})
                m = json.loads(mf.read_text(encoding="utf-8"))
                return self._send_json(200, {
                    "ok": True,
                    "schema": m.get("schema"),
                    "version": m.get("version"),
                    "lang": m.get("lang"),
                    "license": m.get("license"),
                    "asset_count": m.get("asset_count"),
                    "bundle_sha1": m.get("bundle_sha1"),
                })

            if path == "/api/stats":
                pb_count = len(_phrasebook())
                ver = _read_jsonl(VERIFIED_EXT)
                pend = _read_jsonl(PENDING_AUDIT)
                audits = _read_jsonl(AUDIT_LOG)
                avg = (sum(r.get("score", 0.0) for r in ver) / len(ver)) if ver else 0.0
                return self._send_json(200, {
                    "shipped_records": pb_count,
                    "verified_extensions": len(ver),
                    "pending_audit": len(pend),
                    "audit_submissions": len(audits),
                    "avg_verified_score": round(avg, 4),
                })

            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                return self._send_file(WEB_DIR / rel)

            if path.startswith("/data/"):
                rel = path[len("/data/"):]
                return self._send_file(DATA_DIR / rel)

            self.send_error(404, f"No route for {path}")
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[err] {exc}\n{traceback.format_exc()}\n")
            self._send_json(500, {"error": str(exc)})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            body = self._read_body()

            if path == "/api/validate_word":
                return self._handle_validate_word(body)

            if path == "/api/audit_submit":
                return self._handle_audit_submit(body)

            self.send_error(404, f"No POST route for {path}")
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[err] {exc}\n{traceback.format_exc()}\n")
            self._send_json(500, {"error": str(exc)})

    # --- POST impls -------------------------------------------------------
    def _handle_validate_word(self, body: dict) -> None:
        import datetime as dt

        en = (body.get("en") or "").strip()
        sl = (body.get("sl") or "").strip()
        ipa = (body.get("ipa") or "").strip()
        if not en or not sl:
            return self._send_json(400, {"error": "need en + sl"})

        from build.validate.deep_validate import (
            _aggregate, WORD_LAYER_WEIGHTS, VERIFIED_THRESHOLD, MIN_LAYERS_PASS,
            word_layer_L1, word_layer_L2, word_layer_L3, word_layer_L4, word_layer_L5, word_layer_L6,
        )
        from build.g2p.wrapper import g2p as _g2p
        from build.translate.bridge import bridge_en_to_sl

        import sqlite3 as _sql
        conn = _sql.connect(ROOT / "build" / "master.sqlite")
        conn.execute("PRAGMA query_only = 1;")
        cur = conn.cursor()
        cur.execute(
            "SELECT ipa, syllables_json, stress_syllable_idx FROM word_form "
            "WHERE LOWER(surface)=LOWER(?) AND ipa IS NOT NULL "
            "ORDER BY quality_score DESC, id ASC LIMIT 1",
            (sl,),
        )
        row = cur.fetchone()
        sloleks_ipa = row[0] if row else ipa or None
        syll = []
        if row and row[1]:
            try:
                syll = json.loads(row[1])
            except Exception:  # noqa: BLE001
                syll = []
        rec = {
            "sl": sl,
            "en_gloss": en,
            "sloleks_ipa": sloleks_ipa or ipa,
            "syllables": syll,
            "syllable_count": len(syll),
            "audio_path": None,
        }
        layers = {
            "L1": word_layer_L1(rec),
            "L2": word_layer_L2(rec, cur, _g2p),
            "L3": word_layer_L3(rec),
            "L4": word_layer_L4(rec),
            "L5": {"pass": False, "conf": 0.0, "note": "no audio via API"},
            "L6": word_layer_L6(rec, bridge_en_to_sl),
        }
        conn.close()
        score, n_pass = _aggregate(layers, WORD_LAYER_WEIGHTS)
        verified = (score >= VERIFIED_THRESHOLD) and (n_pass >= MIN_LAYERS_PASS)
        record = {
            "ts": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "en": en,
            "sl": sl,
            "ipa": sloleks_ipa or ipa or "",
            "score": score,
            "layer_results": layers,
            "verifier": "api/validate_word",
            "pipeline_version": "SLPROS-1",
        }
        if verified and sl and (sloleks_ipa or ipa):
            _append_jsonl(VERIFIED_EXT, record)
            record["persisted"] = "verified_extensions"
        elif 0.70 <= score < VERIFIED_THRESHOLD:
            _append_jsonl(PENDING_AUDIT, record)
            record["persisted"] = "pending_audit"
        else:
            record["persisted"] = None
        return self._send_json(200, record)

    def _handle_audit_submit(self, body: dict) -> None:
        import datetime as dt

        needed = ("id", "verdict")
        if not all(k in body for k in needed):
            return self._send_json(400, {"error": f"need {needed}"})
        rec = {
            "ts": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "id": body["id"],
            "verdict": body["verdict"],
            "note": body.get("note", ""),
            "payload": body.get("payload"),
        }
        _append_jsonl(AUDIT_LOG, rec)
        return self._send_json(200, {"ok": True, "stored": rec})

    # --- endpoint impl -------------------------------------------------
    def _handle_synthesize(self, en: str) -> None:
        key = normalize_en(en)
        pb = _phrasebook()

        # 1) Phrasebook fast-path
        rec = pb.get(key)
        if rec:
            payload = dict(rec)
            payload["lookup"] = "phrasebook"
            payload["input_en"] = en
            return self._send_json(200, payload)

        # 2) Live translate + synthesize
        syn = _synth()
        res = syn.synthesize(en, lang="en", register="formal")
        sl = res.get("sl", "")
        slpros1 = res.get("slpros1")
        payload = {
            "lookup": "live",
            "input_en": en,
            "en_normalized": key,
            "sl": sl,
            "contour_type": res.get("contour_type"),
            "coverage": res.get("coverage", 0.0),
            "tokens": [
                {
                    "surface": t["surface"],
                    "ipa": t.get("ipa_after_sandhi") or t.get("ipa"),
                    "ipa_pre_sandhi": t.get("ipa"),
                    "upos": t.get("upos"),
                    "role": t.get("role_after_sandhi") or t.get("role"),
                    "source": t.get("source"),
                    "sandhi_notes": t.get("sandhi_notes") or [],
                }
                for t in res.get("tokens", [])
            ],
            "slpros1": slpros1,
            "speech_directive": _directive_for(sl, slpros1),
        }
        return self._send_json(200, payload)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    # Warm the phrasebook so first /api/synthesize isn't slow.
    n = len(_phrasebook())
    print(f"[serve] phrasebook: {n} records", flush=True)
    print(f"[serve] http://{args.host}:{args.port}/", flush=True)
    print("[serve] routes: /  /api/health  /api/synthesize?en=...  /data/...  /static/...",
          flush=True)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] bye", flush=True)
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
