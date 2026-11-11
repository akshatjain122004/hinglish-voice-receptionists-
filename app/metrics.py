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
import math
from dataclasses import dataclass, field
from pathlib import Path
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
    # Set from Sarvam's streaming usage trailer (BUILD_PLAN 5.7a), so the
    # logged turn shows whether prompt size actually drives llm_latency_ms -
    # and doubles as the per-call usage counters task 9.7's budget guard
    # will need.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

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
        "prompt_tokens": timer.prompt_tokens,
        "completion_tokens": timer.completion_tokens,
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

    def mark_usage(self, usage: dict[str, int]) -> None:
        self.timer.prompt_tokens = usage.get("prompt_tokens")
        self.timer.completion_tokens = usage.get("completion_tokens")

    def mark_tts_first_audio(self, now: float, **extra: Any) -> None:
        self.timer.tts_first_audio = now
        if self.timer.speech_end is not None:
            log_turn(self.timer, **extra)


DEFAULT_LOG_PATH = Path("reports/voice_turns.jsonl")


def configure_file_sink(path: str | Path) -> int:
    """Persist every structured turn log line (see `log_turn`) as JSONL.

    `format="{message}"` emits just the JSON payload, no loguru prefix, so
    the file is directly parseable by `load_turns`/`scripts/latency_report.py`.
    Call this once per process, never per call — `logger.add` adds a new
    sink each time, which would duplicate every line across calls in the
    same process. Returns the sink id (`logger.remove(id)` to undo, e.g. in
    a test's teardown).

    Don't call this before `pipecat.runner.run.main()` runs: it calls
    `logger.remove()` at server startup (wiping every existing sink) before
    adding its own stderr one — use `ensure_file_sink` from inside the
    per-call entry point (`app.voice_bot.run_bot`) instead, which configures
    lazily on the first real call, after that reset has already happened.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return logger.add(path, format="{message}", level="INFO")


_file_sink_configured = False


def ensure_file_sink(path: str | Path = DEFAULT_LOG_PATH) -> None:
    """Idempotent `configure_file_sink`, safe to call from every voice call.

    `app.voice_bot.run_bot` calls this on each call rather than once at
    startup, because `pipecat.runner.run.main()` resets logging *after* the
    script's own startup code runs (see `configure_file_sink`'s docstring).
    The guard means the Nth call in a process doesn't add the Nth duplicate
    sink, which would otherwise log every subsequent turn N times over.
    """
    global _file_sink_configured
    if _file_sink_configured:
        return
    configure_file_sink(path)
    _file_sink_configured = True


def load_turns(path: str | Path) -> list[dict[str, Any]]:
    """Parse a JSONL metrics log, keeping only completed-turn records.

    The log file can contain other app log lines (e.g. "Caller connected")
    sharing the same sink, and partial turns that never reached TTS (e.g. a
    tool error) — both are skipped, since only `total_latency_ms` marks a
    turn as having gone all the way through the pipeline.
    """
    turns = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and "total_latency_ms" in record:
            turns.append(record)
    return turns


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile (`p` in `[0, 100]`) of `values`."""
    if not values:
        raise ValueError("percentile() requires at least one value")
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


_STAGE_KEYS = ("stt_latency_ms", "llm_latency_ms", "tts_latency_ms", "total_latency_ms")


def latency_summary(
    turns: list[dict[str, Any]], *, vad_stop_secs: float = 0.0
) -> dict[str, dict[str, float]]:
    """p50/p95/n per pipeline stage, across whichever turns have that stage.

    A negative duration is physically impossible — a symptom of
    `TurnTracker`'s known overlapping-turns limitation (a caller's next
    utterance, or a multi-sentence reply's next TTS clip, arriving before
    the previous turn's marks finish — see docs/BUILD_PLAN.md phase 4
    notes), not a real measurement. Dropped rather than skewing the
    percentiles of the turns that are legitimate; `dropped` counts how many.

    `vad_stop_secs` adds a `perceived_total_ms` stage next to
    `total_latency_ms` (BUILD_PLAN 5.0b): `speech_end` is stamped from
    `VADUserStoppedSpeakingFrame`, which Silero only creates `vad_stop_secs`
    *after* the caller's actual last word (see `app.voice_bot.VAD_STOP_SECS`'s
    docstring) — so `total_latency_ms` alone understates what the caller
    really waits. Adding a fixed offset to every already-computed percentile
    is equivalent to adding it to every raw value first (it's a shift, not a
    rescale) without re-deriving them. Left out entirely when `vad_stop_secs`
    is 0 (the default) or `total_latency_ms` itself has no data.
    """
    summary = {}
    for stage in _STAGE_KEYS:
        raw_values = [t[stage] for t in turns if stage in t]
        values = [v for v in raw_values if v >= 0]
        if not values:
            continue
        summary[stage] = {
            "p50": percentile(values, 50),
            "p95": percentile(values, 95),
            "n": len(values),
            "dropped": len(raw_values) - len(values),
        }
    if vad_stop_secs and "total_latency_ms" in summary:
        offset_ms = vad_stop_secs * 1000
        total = summary["total_latency_ms"]
        summary["perceived_total_ms"] = {
            "p50": total["p50"] + offset_ms,
            "p95": total["p95"] + offset_ms,
            "n": total["n"],
            "dropped": total["dropped"],
        }
    return summary


def render_latency_report(
    summary: dict[str, dict[str, float]], *, title: str = "Latency report"
) -> str:
    lines = [
        f"# {title}",
        "",
        "| stage | n | p50 (ms) | p95 (ms) | dropped (negative) |",
        "|---|---|---|---|---|",
    ]
    for stage, stats in summary.items():
        dropped = stats.get("dropped", 0)
        lines.append(
            f"| {stage} | {stats['n']} | {stats['p50']:.0f} | {stats['p95']:.0f} | {dropped} |"
        )
    return "\n".join(lines) + "\n"
