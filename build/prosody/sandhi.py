"""Slovenian sandhi and clitic rules.

Deterministic rules applied to an ordered list of word tokens *after* word-level IPA has been
assigned, but *before* sentence-level prosody is generated. Each rule knows its trigger context
(usually a (left, right) word-pair condition), produces a modified IPA sequence, and attaches
prosodic metadata (clitic host, pause suppression, etc.).

The phonological processes covered here are the ones most important for natural-sounding
concatenative synthesis of the MVP corpus:

  R1. Prepositional proclitic ``v`` surfaces as [u] before a voiced consonant and as [f] before a
      voiceless one; it forms one prosodic unit with the host.
  R2. Word-final voiced obstruent → voiceless (Auslautverhärtung): /ɡraːd/ → [ɡraːt].
  R3. Regressive voicing assimilation across a word boundary: the last obstruent of word₁ takes
      the voicing of the first obstruent of word₂.
  R4. Vowel elision: two identical unstressed vowels across a word boundary may reduce to one in
      informal register.
  R5. Monosyllabic negative/conjunction clitics (``je``, ``ne``, ``se``, ``bi``, ``sem``,
      ``si``) attach prosodically to an adjacent content word, suppressing inter-token pause and
      dropping their own stress.

Each rule returns a TokenChange describing the modification so downstream code (contour_model)
can honour clitic groups, merged vowels, and devoicing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Sets used in the rules below
VOICED_OBSTRUENTS = set("bdɡgvzʒ")
VOICELESS_OBSTRUENTS = set("ptkfsʃx")
VOICELESS_MAP = {"b": "p", "d": "t", "ɡ": "k", "g": "k", "z": "s", "ʒ": "ʃ", "v": "f"}
VOICED_MAP = {"p": "b", "t": "d", "k": "ɡ", "s": "z", "ʃ": "ʒ", "f": "v"}

# Clitics: stressless function words that prosodically attach to a neighbour.
CLITICS_PROCLITIC = {"v", "s", "k", "z", "na", "po", "pri", "od", "do", "iz", "za", "pred"}
CLITICS_ENCLITIC = {"je", "ne", "se", "si", "bi", "sem", "sva", "smo", "ste", "so", "te", "me", "ga"}


@dataclass
class Token:
    surface: str
    ipa: str
    role: str = "content"  # content | function | clitic | punct
    pause_after_ms: int = 0
    host_index: int | None = None  # when clitic, index of the prosodic host token
    notes: list[str] = field(default_factory=list)
    # Optional UD features: when populated, downstream SLPROS-1 can blend in the
    # empirical (upos, deprel, pos_bin) CPT prior from build/_prosody_cpt.json.
    upos: str | None = None
    deprel: str | None = None


@dataclass
class SentenceTokens:
    tokens: list[Token]
    register: str = "formal"

    def to_debug(self) -> list[dict]:
        return [
            {
                "i": i,
                "surface": t.surface,
                "ipa": t.ipa,
                "role": t.role,
                "pause_after_ms": t.pause_after_ms,
                "host_index": t.host_index,
                "notes": list(t.notes),
            }
            for i, t in enumerate(self.tokens)
        ]


def _first_consonant(ipa: str) -> str | None:
    s = re.sub(r"[ˈˌ\s]", "", ipa)
    if not s:
        return None
    return s[0]


def _last_consonant(ipa: str) -> str | None:
    s = re.sub(r"[ˈˌ\s]", "", ipa)
    # strip a trailing length mark so we look at a phoneme, not a diacritic
    s = s.rstrip("ːʰ")
    if not s:
        return None
    return s[-1]


# ---- Individual rule implementations ---------------------------------------------------------

def rule_prep_v_proclitic(sent: SentenceTokens) -> None:
    """R1: ``v`` + word → [u] before voiced, [f] before voiceless, proclitic attachment."""
    for i, tok in enumerate(sent.tokens[:-1]):
        if tok.surface.lower() != "v":
            continue
        nxt = sent.tokens[i + 1]
        c = _first_consonant(nxt.ipa)
        if c and c in VOICELESS_OBSTRUENTS:
            tok.ipa = "f"
        else:
            tok.ipa = "u"
        tok.role = "clitic"
        tok.host_index = i + 1
        tok.pause_after_ms = 0
        tok.notes.append("R1:prep_v_proclitic")


def rule_final_devoicing(sent: SentenceTokens) -> None:
    """R2: word-final voiced obstruent → voiceless unless the next token begins with a voiced obstruent."""
    for i, tok in enumerate(sent.tokens):
        if tok.role == "clitic":
            continue
        last = _last_consonant(tok.ipa)
        if not last or last not in VOICED_MAP.values():
            continue
        if last not in VOICED_OBSTRUENTS:
            continue
        # check next token
        nxt = sent.tokens[i + 1] if i + 1 < len(sent.tokens) else None
        if nxt and nxt.role != "punct":
            c = _first_consonant(nxt.ipa)
            if c and c in VOICED_OBSTRUENTS:
                continue  # voicing assimilation handled by R3
        # apply devoicing: replace the final phoneme
        idx = tok.ipa.rfind(last)
        if idx >= 0:
            tok.ipa = tok.ipa[:idx] + VOICELESS_MAP[last] + tok.ipa[idx + 1 :]
            tok.notes.append("R2:final_devoicing")


def rule_regressive_voicing(sent: SentenceTokens) -> None:
    """R3: the final obstruent of word₁ agrees in voicing with the initial obstruent of word₂."""
    for i in range(len(sent.tokens) - 1):
        t1, t2 = sent.tokens[i], sent.tokens[i + 1]
        if t1.role == "punct" or t2.role == "punct":
            continue
        last = _last_consonant(t1.ipa)
        first = _first_consonant(t2.ipa)
        if not last or not first:
            continue
        if last in VOICELESS_OBSTRUENTS and first in VOICED_OBSTRUENTS:
            mapped = VOICED_MAP.get(last)
            if mapped:
                idx = t1.ipa.rfind(last)
                t1.ipa = t1.ipa[:idx] + mapped + t1.ipa[idx + 1 :]
                t1.notes.append("R3:regressive_voicing")
        elif last in VOICED_OBSTRUENTS and first in VOICELESS_OBSTRUENTS:
            mapped = VOICELESS_MAP.get(last)
            if mapped:
                idx = t1.ipa.rfind(last)
                t1.ipa = t1.ipa[:idx] + mapped + t1.ipa[idx + 1 :]
                t1.notes.append("R3:regressive_devoicing")


def rule_vowel_elision(sent: SentenceTokens) -> None:
    """R4 (informal only): drop a final unstressed vowel when the next word begins with the same vowel."""
    if sent.register != "informal":
        return
    for i in range(len(sent.tokens) - 1):
        t1, t2 = sent.tokens[i], sent.tokens[i + 1]
        if not t1.ipa or not t2.ipa:
            continue
        last = t1.ipa.rstrip("ːˈˌ")[-1:]
        first = t2.ipa.lstrip("ˈˌ")[0:1]
        if last and last == first and last in set("aeiouɛɔə"):
            t1.ipa = t1.ipa[:-1]
            t1.notes.append("R4:vowel_elision")


def rule_clitic_attachment(sent: SentenceTokens) -> None:
    """R5: enclitic/proclitic stressless attachment of common function words."""
    for i, tok in enumerate(sent.tokens):
        s = tok.surface.lower()
        if s in CLITICS_ENCLITIC and i > 0:
            tok.role = "clitic"
            tok.host_index = i - 1
            tok.pause_after_ms = 0
            tok.notes.append("R5:enclitic")
        elif s in CLITICS_PROCLITIC and i + 1 < len(sent.tokens):
            if tok.role != "clitic":  # R1 may already have promoted `v`
                tok.role = "clitic"
                tok.host_index = i + 1
                tok.pause_after_ms = 0
                tok.notes.append("R5:proclitic")


# ---- Pipeline orchestration --------------------------------------------------------------------

DEFAULT_RULES = (
    rule_prep_v_proclitic,
    rule_clitic_attachment,
    rule_regressive_voicing,
    rule_final_devoicing,
    rule_vowel_elision,
)


def apply_sandhi(sent: SentenceTokens, rules=DEFAULT_RULES) -> SentenceTokens:
    """Apply the configured rule pipeline in order. Returns the same (mutated) SentenceTokens."""
    for rule in rules:
        rule(sent)
    return sent
