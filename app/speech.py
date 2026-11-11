"""Converts digit-written times, prices and phone numbers in agent replies
into words a TTS voice can speak naturally (BUILD_PLAN 5.6). This turns
CLAUDE.md's "write numbers so they can be spoken" prompt rule into code,
instead of trusting the LLM to always remember it.

Pure, no pipecat imports — same split as app/metrics.py. The voice pipeline
calls `normalise_for_speech` on a whole aggregated sentence, via Sarvam TTS's
own `text_transforms` hook (see app/voice_bot.py), never on a partial
streamed chunk — a digital time like "17:30" can arrive as "17:" and "30" in
separate chunks (since Phase 5.1's streaming), and only the TTS service sees
the already-reassembled sentence. That hook also only ever changes what
reaches the synthesizer: `Agent`'s history and `CallLog`'s transcript always
keep the model's original text, so the evals (which grade that original
text) are unaffected.
"""

from __future__ import annotations

import re

# 0-19 covers every value these normalisers ever need: hours (1-12), the
# hundreds/thousands digit of a clinic price (clinic.yaml's prices are all
# round hundreds under 2000, or round thousands - see _price_words), and
# single phone-number digits (0-9). Deliberately not a general 0-99+ table:
# Hindi number words past 19 are irregular in a way that would need a much
# larger hand-written list to get right, and nothing in this domain needs it.
_HI_WORDS = {
    0: "zero",  # borrowed from English even in Hindi mode - how phone
    # numbers are actually read aloud in Hindi/Hinglish; "shunya" is correct
    # but unusually formal for this context.
    1: "ek",
    2: "do",
    3: "teen",
    4: "chaar",
    5: "paanch",
    6: "chhe",
    7: "saat",
    8: "aath",
    9: "nau",
    10: "das",
    11: "gyarah",
    12: "baarah",
    13: "terah",
    14: "chaudah",
    15: "pandrah",
    16: "solah",
    17: "satrah",
    18: "atharah",
    19: "unnees",
}

_EN_WORDS = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
}

# A modest set of common Hindi/Hinglish marker words, reusing vocabulary
# app.timeparse already parses, for detect_lang()'s heuristic - see its
# docstring for exactly what this is (and isn't) used for.
_HINGLISH_MARKER_WORDS = {
    "hai",
    "hain",
    "kya",
    "aap",
    "kal",
    "aaj",
    "parso",
    "baje",
    "subah",
    "dopahar",
    "shaam",
    "sham",
    "raat",
    "saade",
    "paune",
    "sava",
    "rupaye",
    "haan",
    "nahi",
    "nahin",
    "theek",
    "dhanyavaad",
    "namaste",
    "ho",
    "hoga",
    "hogi",
    "honge",
    "karein",
    "kijiye",
    "kijiyega",
    "milega",
    "milegi",
    "chahiye",
    "lagta",
    "lagti",
    "sakte",
    "sakta",
    "sakti",
    "liye",
    "yahan",
    "yeh",
    "woh",
    "aapka",
    "aapki",
    "humara",
}

_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
_WORD_RE = re.compile(r"[a-zA-Z]+")


def detect_lang(text: str) -> str:
    """A narrow heuristic: "hi" (Hindi/Hinglish) or "en" (English).

    Scoped to exactly one decision - which number-word style
    `normalise_for_speech` should use for a sentence - not general-purpose
    language identification. Devanagari script is an unambiguous "hi"; for
    romanised text, any common Hindi/Hinglish marker word (reusing
    app.timeparse's own vocabulary) also counts as "hi", since CLAUDE.md's
    bot is Hinglish-in-Hinglish-out and a sentence with even one Hindi word
    should get Hindi-style numbers. Pure English (no markers, no Devanagari)
    is "en".
    """
    if _DEVANAGARI_RE.search(text):
        return "hi"
    words = {w.lower() for w in _WORD_RE.findall(text)}
    if words & _HINGLISH_MARKER_WORDS:
        return "hi"
    return "en"


def _word(n: int, lang: str) -> str:
    return (_HI_WORDS if lang != "en" else _EN_WORDS)[n]


def _hour12(hour24: int) -> int:
    h = hour24 % 12
    return 12 if h == 0 else h


def _time_words(hour24: int, minute: int, lang: str) -> str | None:
    """None for anything but a quarter-hour time - clinic.yaml's
    slot_minutes is 15, so every real booking/clinic-hours time is one of
    :00/:15/:30/:45. Anything else is left exactly as written rather than
    guessed at (a known, documented limitation, not a crash)."""
    hour_word = _word(_hour12(hour24), lang)
    if minute == 0:
        return f"{hour_word} baje" if lang != "en" else f"{hour_word} o'clock"
    if minute == 15:
        return f"sava {hour_word} baje" if lang != "en" else f"quarter past {hour_word}"
    if minute == 30:
        return f"saade {hour_word} baje" if lang != "en" else f"half past {hour_word}"
    if minute == 45:
        next_word = _word(_hour12(hour24 + 1), lang)
        return f"paune {next_word} baje" if lang != "en" else f"quarter to {next_word}"
    return None


_TIME_RE = re.compile(
    # A leading sava/paune/saade or a trailing baje is consumed into the
    # match (and dropped - the digits are the source of truth) rather than
    # left in place, so a reply that writes both forms together (a real,
    # observed LLM slip - see the Phase 3 close-out note on "10 baje") gets
    # one correct spoken form instead of a duplicated one ("das baje baje").
    r"(?:\b(?:sava|paune|saade)\s+)?\b([01]?\d|2[0-3]):([0-5]\d)\b(?:\s*baje\b)?",
    re.IGNORECASE,
)


def _normalise_times(text: str, lang: str) -> str:
    def repl(m: re.Match[str]) -> str:
        words = _time_words(int(m.group(1)), int(m.group(2)), lang)
        return words if words is not None else m.group(0)

    return _TIME_RE.sub(repl, text)


def _price_words(amount: int, lang: str) -> str | None:
    """None for anything that isn't a round hundred - clinic.yaml's service
    prices all are (200/500/1500/3000/4000 as of Phase 5); a non-round
    amount is left exactly as written, same reasoning as `_time_words`."""
    if amount <= 0 or amount % 100 != 0:
        return None
    suffix = "rupaye" if lang != "en" else "rupees"
    hundred_word = "sau" if lang != "en" else "hundred"
    if amount < 2000:
        hundreds = amount // 100
        if hundreds > 19:
            return None
        return f"{_word(hundreds, lang)} {hundred_word} {suffix}"
    thousand_word = "hazar" if lang != "en" else "thousand"
    thousands, remainder = divmod(amount, 1000)
    remainder_hundreds = remainder // 100
    if thousands > 19 or remainder_hundreds > 19:
        return None
    if remainder_hundreds == 0:
        return f"{_word(thousands, lang)} {thousand_word} {suffix}"
    return (
        f"{_word(thousands, lang)} {thousand_word} "
        f"{_word(remainder_hundreds, lang)} {hundred_word} {suffix}"
    )


_PRICE_RE = re.compile(r"(?:₹|Rs\.?\s?)(\d+)\b")


def _normalise_prices(text: str, lang: str) -> str:
    def repl(m: re.Match[str]) -> str:
        words = _price_words(int(m.group(1)), lang)
        return words if words is not None else m.group(0)

    return _PRICE_RE.sub(repl, text)


_PHONE_RE = re.compile(r"\+?\d{10,13}\b")


def _phone_words(digits: str, lang: str) -> str:
    """Digit by digit, grouped in pairs with a comma pause between groups
    (BUILD_PLAN 5.6's "phone numbers read in pairs") - not spoken as
    two-digit numbers. Hindi's two-digit number words (21-99) are
    famously irregular; reading pairs digit-by-digit stays unambiguous and
    correct without needing that whole table, and "pairs" is read here as
    pacing for the listener, not a request for two-digit number words."""
    table = _HI_WORDS if lang != "en" else _EN_WORDS
    words = [table[int(d)] for d in digits]
    pairs = [" ".join(words[i : i + 2]) for i in range(0, len(words), 2)]
    return ", ".join(pairs)


def _normalise_phones(text: str, lang: str) -> str:
    def repl(m: re.Match[str]) -> str:
        return _phone_words(m.group(0).lstrip("+"), lang)

    return _PHONE_RE.sub(repl, text)


def normalise_for_speech(text: str, lang: str) -> str:
    """Rewrites digital times, prices and phone numbers in `text` for TTS.

    `lang` is `"hi"` (Hindi/Hinglish number words) or `"en"` (English);
    anything else is treated as `"hi"`, matching this bot's Hinglish-by-default
    voice. Text with no matching pattern (including already-spoken text, e.g.
    "paanch baje") is returned unchanged. Call `detect_lang` first if the
    caller's language for this sentence isn't already known.
    """
    text = _normalise_times(text, lang)
    text = _normalise_prices(text, lang)
    text = _normalise_phones(text, lang)
    return text
