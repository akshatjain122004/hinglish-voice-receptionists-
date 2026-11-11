"""Filters STT noise before it reaches the agent (BUILD_PLAN 5.8).

Pure string logic, no pipecat imports — same split as app/metrics.py, so
this stays trivially unit-testable.
"""

from __future__ import annotations

import unicodedata

MIN_REAL_TRANSCRIPT_LENGTH = 2


def is_noise(text: str) -> bool:
    """True if `text` is too short to be a real caller utterance.

    Strips whitespace and punctuation (including Devanagari `।`/`॥`, not
    just ASCII `.`/`,`) and counts what's left in Unicode code points, not
    bytes or words — a short Hindi "yes" like "हाँ" or "जी" is 2-3 code
    points, well short of a word boundary, but it's a real booking
    confirmation (CLAUDE.md's non-negotiable confirm-before-booking rule)
    and must never be dropped. Devanagari vowel signs/nasalization marks
    (categories Mc/Mn) are letters' combining parts, not punctuation, so
    they're kept — stripping by `str.isalnum()` alone would wrongly treat
    them as punctuation and undercount real Hindi words.
    """
    kept = [ch for ch in text if not ch.isspace() and unicodedata.category(ch)[0] != "P"]
    return len(kept) < MIN_REAL_TRANSCRIPT_LENGTH
