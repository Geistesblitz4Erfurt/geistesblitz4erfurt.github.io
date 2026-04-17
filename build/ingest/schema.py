"""SQLite schema + DB helpers for the build pipeline.

Single-file master DB at build/master.sqlite. All build steps read/write through this module.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lemma (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    lemma     TEXT NOT NULL UNIQUE,
    pos       TEXT,
    freq_rank INTEGER,
    gos_freq  INTEGER
);

CREATE TABLE IF NOT EXISTS word_form (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    lemma_id            INTEGER REFERENCES lemma(id),
    surface             TEXT NOT NULL,
    msd                 TEXT,
    ipa                 TEXT,
    xsampa              TEXT,
    accent_class        TEXT,       -- RL | FL | RS | FS | -
    syllables_json      TEXT,       -- JSON array of syllable objects
    stress_syllable_idx INTEGER,
    quality_score       REAL DEFAULT 0.0,
    source_mask         INTEGER DEFAULT 0,
    UNIQUE(surface, msd)
);
CREATE INDEX IF NOT EXISTS idx_word_form_surface ON word_form(surface);

CREATE TABLE IF NOT EXISTS audio_asset (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    local_path     TEXT NOT NULL,
    format         TEXT,
    source         TEXT,
    license        TEXT,
    duration_ms    INTEGER,
    checksum       TEXT,
    speaker_meta   TEXT,
    f0_baseline_hz REAL,
    word_form_id   INTEGER REFERENCES word_form(id)
);
CREATE INDEX IF NOT EXISTS idx_audio_word_form ON audio_asset(word_form_id);

CREATE TABLE IF NOT EXISTS sentence (
    id              TEXT PRIMARY KEY,
    category        TEXT NOT NULL,
    register        TEXT,
    intonation      TEXT,
    sl_text         TEXT NOT NULL,
    en_text         TEXT,
    de_text         TEXT,
    prosody_json    TEXT,
    source_template TEXT
);

CREATE TABLE IF NOT EXISTS sentence_token (
    sentence_id      TEXT REFERENCES sentence(id) ON DELETE CASCADE,
    pos_in_sentence  INTEGER,
    surface          TEXT,
    word_form_id     INTEGER REFERENCES word_form(id),
    phrase_role      TEXT,     -- content | function | clitic | punct
    pause_after_ms   INTEGER,
    f0_contour_tag   TEXT,
    PRIMARY KEY (sentence_id, pos_in_sentence)
);

CREATE TABLE IF NOT EXISTS context_rule (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE,
    pattern     TEXT,
    replacement TEXT,
    scope       TEXT,          -- word | phrase | sentence
    type        TEXT,          -- sandhi | assimilation | elision | cliticization
    priority    INTEGER DEFAULT 100
);

CREATE TABLE IF NOT EXISTS validation_issue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT,
    severity     TEXT,    -- info | warn | error
    entity_kind  TEXT,    -- word_form | sentence | audio
    entity_id    TEXT,
    message      TEXT,
    details_json TEXT
);
"""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA_SQL)
    return conn


def upsert_sentences(conn: sqlite3.Connection, sentences: Iterable) -> int:
    n = 0
    with conn:
        for s in sentences:
            conn.execute(
                """INSERT OR REPLACE INTO sentence
                     (id, category, register, intonation, sl_text, en_text, de_text, source_template)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    s.id,
                    s.category,
                    getattr(s, "register", None),
                    getattr(s, "intonation", None),
                    s.sl,
                    s.en,
                    getattr(s, "de", None),
                    getattr(s, "source_template", None),
                ),
            )
            n += 1
    return n


def record_issue(
    conn: sqlite3.Connection,
    kind: str,
    severity: str,
    entity_kind: str,
    entity_id: str,
    message: str,
    details: dict | None = None,
) -> None:
    with conn:
        conn.execute(
            """INSERT INTO validation_issue
                 (kind, severity, entity_kind, entity_id, message, details_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (kind, severity, entity_kind, entity_id, message, json.dumps(details or {})),
        )


SOURCE_SLOLEKS = 1 << 0
SOURCE_WIKTIONARY = 1 << 1
SOURCE_G2P = 1 << 2
SOURCE_FORVO_VALIDATED = 1 << 3
SOURCE_LINGUALIBRE = 1 << 4
