"""Turn Hinglish/Hindi/English date-and-time phrases into datetimes.

Pure, deterministic parsing — no LLM involved, so `agent.py` and the eval
suite can trust the result. Covers the phrase shapes a caller actually
uses on the phone: relative days (aaj/kal/parso), weekday names (Hindi and
English), parts of day (subah/dopahar/shaam/raat), Hindi half/quarter time
words (saade/paune/sava) and plain digital/clock times.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

NUM_WORDS = {
    "ek": 1,
    "do": 2,
    "teen": 3,
    "char": 4,
    "chaar": 4,
    "paanch": 5,
    "panch": 5,
    "chhe": 6,
    "che": 6,
    "saat": 7,
    "aath": 8,
    "ath": 8,
    "nau": 9,
    "das": 10,
    "dus": 10,
    "gyarah": 11,
    "gyara": 11,
    "baarah": 12,
    "barah": 12,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

NUM_PATTERN = r"(\d{1,2}|" + "|".join(sorted(NUM_WORDS, key=len, reverse=True)) + r")"

WEEKDAYS = {
    "monday": 0,
    "somvaar": 0,
    "somvar": 0,
    "tuesday": 1,
    "mangalvar": 1,
    "mangalwar": 1,
    "wednesday": 2,
    "budhvar": 2,
    "budhwar": 2,
    "thursday": 3,
    "guruvar": 3,
    "brihaspativar": 3,
    "brihaspatiwar": 3,
    "friday": 4,
    "shukravar": 4,
    "shukrawar": 4,
    "saturday": 5,
    "shanivar": 5,
    "shaniwar": 5,
    "sunday": 6,
    "raviwar": 6,
    "ravivar": 6,
    "itwar": 6,
}

PERIOD_WORDS = {
    "subah": "am",
    "morning": "am",
    "dopahar": "pm",
    "afternoon": "pm",
    "shaam": "pm",
    "sham": "pm",
    "evening": "pm",
    "raat": "pm",
    "night": "pm",
}

NIGHT_WORDS = {"raat", "night"}


class TimeParseError(ValueError):
    """Raised when no date or no time could be found in the phrase."""


def _num(token: str) -> int:
    return int(token) if token.isdigit() else NUM_WORDS[token]


def _resolve_date(text: str, now: datetime) -> datetime.date | None:
    if re.search(r"\bparso\b", text):
        return (now + timedelta(days=2)).date()
    if re.search(r"\bday after tomorrow\b", text):
        return (now + timedelta(days=2)).date()
    if re.search(r"\bkal\b", text):
        return (now + timedelta(days=1)).date()
    if re.search(r"\btomorrow\b", text):
        return (now + timedelta(days=1)).date()
    if re.search(r"\baaj\b", text) or re.search(r"\btoday\b", text):
        return now.date()

    for word, weekday in WEEKDAYS.items():
        if re.search(rf"\b{word}\b", text):
            days_ahead = (weekday - now.weekday()) % 7
            return (now + timedelta(days=days_ahead)).date()

    return None


def _explicit_period(text: str) -> str | None:
    for word, period in PERIOD_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return period
    return None


def _default_period(hour12: int) -> str:
    """A clinic is open 10:00-20:00, so an unqualified hour is most likely
    that business-hours reading: 8-11 -> morning, 1-7 and 12 -> afternoon/
    evening (noon counts as midday, i.e. "pm")."""
    if 8 <= hour12 <= 11:
        return "am"
    return "pm"


def _to_24h(hour12: int, period: str) -> int:
    if period == "am":
        return 0 if hour12 == 12 else hour12
    return 12 if hour12 == 12 else hour12 + 12


def _resolve_time(text: str) -> tuple[int, int] | None:
    patterns: list[tuple[str, callable]] = [
        (r"half past " + NUM_PATTERN, lambda m: (_num(m.group(1)), 30)),
        (r"quarter to " + NUM_PATTERN, lambda m: (_num(m.group(1)) - 1, 45)),
        (r"quarter past " + NUM_PATTERN, lambda m: (_num(m.group(1)), 15)),
        (r"saade " + NUM_PATTERN, lambda m: (_num(m.group(1)), 30)),
        (r"paune " + NUM_PATTERN, lambda m: (_num(m.group(1)) - 1, 45)),
        (r"sava " + NUM_PATTERN, lambda m: (_num(m.group(1)), 15)),
        (r"(\d{1,2}):(\d{2})\s*(am|pm)?", None),
        (NUM_PATTERN + r"\s*baje", lambda m: (_num(m.group(1)), 0)),
        (r"(\d{1,2})\s*(am|pm)", None),
    ]

    for pattern, builder in patterns:
        match = re.search(pattern, text)
        if not match:
            continue

        if pattern.startswith(r"(\d{1,2}):(\d{2})"):
            hour12 = int(match.group(1))
            minute = int(match.group(2))
            explicit = match.group(3)
        elif pattern.endswith(r"(am|pm)"):
            hour12 = int(match.group(1))
            minute = 0
            explicit = match.group(2)
        else:
            hour12, minute = builder(match)
            explicit = None

        if hour12 == 0:
            hour12 = 12

        period = explicit or _explicit_period(text) or _default_period(hour12)
        is_night = any(re.search(rf"\b{word}\b", text) for word in NIGHT_WORDS)
        if hour12 == 12 and period == "pm" and is_night and not explicit:
            return 0, minute
        return _to_24h(hour12, period), minute

    return None


def parse(text: str, *, now: datetime) -> datetime:
    """Parse a Hinglish/Hindi/English date-and-time phrase relative to `now`."""
    normalised = text.lower()

    date_part = _resolve_date(normalised, now)
    time_part = _resolve_time(normalised)
    if date_part is None or time_part is None:
        raise TimeParseError(f"could not parse a date and time from: {text!r}")

    hour, minute = time_part
    return datetime.combine(date_part, datetime.min.time(), tzinfo=now.tzinfo).replace(
        hour=hour, minute=minute
    )
