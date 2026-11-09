"""Per-turn voice latency metrics.

One `TurnTimer` per voice turn, timestamping speech end, STT final, LLM first
token and TTS first audio byte (epoch seconds, like `time.time()`), and one
structured JSON line logged per turn — see CLAUDE.md's logging rule.

This module is pipecat-agnostic on purpose: it only knows timestamps and
JSON, so it stays trivially unit-testable with synthetic data. `app/voice_bot.py`
is what actually marks these timestamps from real pipeline frames.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

# (duration key, start field, end field)
_STAGES: tuple[tuple[str, str, str], ...] = (
    ("stt_latency_ms", "speech_end", "stt_final"),
    ("llm_latency_ms", "stt_final", "llm_first_token"),
    ("tts_latency_ms", "llm_first_token", "tts_first_audio"),
    ("total_latency_ms", "speech_end", "tts_first_audio"),
)


@dataclass
class TurnTimer:
    """Wall-clock timestamps for one voice turn's pipeline stages."""

    speech_end: float | None = None
    stt_final: float | None = None
    llm_first_token: float | None = None
    tts_first_audio: float | None = None

    def durations_ms(self) -> dict[str, float]:
        """Per-stage durations in milliseconds.

        A stage is only included once both its start and end timestamps are
        set, so a turn that never reaches TTS (e.g. a tool error) still
        reports whatever stages it did complete.
        """
        values = {
            "speech_end": self.speech_end,
            "stt_final": self.stt_final,
            "llm_first_token": self.llm_first_token,
            "tts_first_audio": self.tts_first_audio,
        }
        return {
            name: (values[end] - values[start]) * 1000
            for name, start, end in _STAGES
            if values[start] is not None and values[end] is not None
        }


def turn_log_line(timer: TurnTimer, **extra: Any) -> str:
    """One structured JSON line: stage timestamps, computed durations, extra fields."""
    payload = {
        "speech_end": timer.speech_end,
        "stt_final": timer.stt_final,
        "llm_first_token": timer.llm_first_token,
        "tts_first_audio": timer.tts_first_audio,
        **timer.durations_ms(),
        **extra,
    }
    return json.dumps(payload)


def log_turn(timer: TurnTimer, **extra: Any) -> None:
    logger.info(turn_log_line(timer, **extra))


@dataclass
class TurnTracker:
    """Shared, mutable holder for the in-progress turn's `TurnTimer`.

    `AgentProcessor` (app/voice_bot.py) marks `speech_end`/`stt_final`/
    `llm_first_token` as a turn moves through STT and the agent; a TTS-side
    marker further down the pipeline marks `tts_first_audio` and logs the
    finished turn — it's the last stage, so it's the natural place to log.
    """

    timer: TurnTimer = field(default_factory=TurnTimer)

    def mark_speech_end(self, now: float) -> None:
        self.timer = TurnTimer(speech_end=now)

    def mark_stt_final(self, now: float) -> None:
        self.timer.stt_final = now

    def mark_llm_first_token(self, now: float) -> None:
        self.timer.llm_first_token = now

    def mark_tts_first_audio(self, now: float, **extra: Any) -> None:
        self.timer.tts_first_audio = now
        if self.timer.speech_end is not None:
            log_turn(self.timer, **extra)
