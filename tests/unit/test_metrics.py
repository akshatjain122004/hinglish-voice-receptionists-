import json

import pytest
from loguru import logger

from app import metrics
from app.metrics import (
    TurnTimer,
    TurnTracker,
    configure_file_sink,
    ensure_file_sink,
    latency_summary,
    load_turns,
    log_turn,
    percentile,
    render_latency_report,
    turn_log_line,
)


def test_durations_ms_computes_all_four_stages():
    timer = TurnTimer(
        speech_end=100.0, stt_final=100.3, llm_first_token=101.1, tts_first_audio=101.4
    )

    durations = timer.durations_ms()

    assert durations["stt_latency_ms"] == pytest.approx(300.0)
    assert durations["llm_latency_ms"] == pytest.approx(800.0)
    assert durations["tts_latency_ms"] == pytest.approx(300.0)
    assert durations["total_latency_ms"] == pytest.approx(1400.0)


def test_durations_ms_omits_stages_missing_a_timestamp():
    timer = TurnTimer(speech_end=100.0, stt_final=100.3)

    durations = timer.durations_ms()

    assert durations == {"stt_latency_ms": pytest.approx(300.0)}


def test_durations_ms_empty_timer_has_no_durations():
    assert TurnTimer().durations_ms() == {}


def test_turn_log_line_is_valid_json_with_timestamps_durations_and_extra_fields():
    timer = TurnTimer(
        speech_end=100.0, stt_final=100.5, llm_first_token=101.0, tts_first_audio=101.5
    )

    line = turn_log_line(timer, session_id="call-1")
    data = json.loads(line)

    assert data["session_id"] == "call-1"
    assert data["speech_end"] == 100.0
    assert data["stt_final"] == 100.5
    assert data["llm_first_token"] == 101.0
    assert data["tts_first_audio"] == 101.5
    assert data["total_latency_ms"] == pytest.approx(1500.0)


def test_turn_log_line_includes_prompt_and_completion_tokens():
    """BUILD_PLAN 5.7a: logged next to llm_latency_ms, to see whether prompt
    size actually drives time-to-first-token."""
    timer = TurnTimer(speech_end=100.0, prompt_tokens=120, completion_tokens=18)

    data = json.loads(turn_log_line(timer))

    assert data["prompt_tokens"] == 120
    assert data["completion_tokens"] == 18


def test_turn_log_line_tokens_are_none_when_never_marked():
    data = json.loads(turn_log_line(TurnTimer()))

    assert data["prompt_tokens"] is None
    assert data["completion_tokens"] is None


class TestTurnTrackerUsage:
    def test_mark_usage_sets_prompt_and_completion_tokens(self):
        tracker = TurnTracker()

        tracker.mark_usage({"prompt_tokens": 90, "completion_tokens": 12})

        assert tracker.timer.prompt_tokens == 90
        assert tracker.timer.completion_tokens == 12

    def test_mark_usage_tolerates_a_usage_dict_missing_a_key(self):
        """Sarvam's own documented trailer ({"total_tokens": N} alone) has
        been seen without prompt_tokens/completion_tokens in earlier
        testing - this must not raise."""
        tracker = TurnTracker()

        tracker.mark_usage({"total_tokens": 50})

        assert tracker.timer.prompt_tokens is None
        assert tracker.timer.completion_tokens is None

    def test_later_round_usage_overwrites_an_earlier_rounds(self):
        tracker = TurnTracker()

        tracker.mark_usage({"prompt_tokens": 100, "completion_tokens": 5})
        tracker.mark_usage({"prompt_tokens": 150, "completion_tokens": 8})

        assert tracker.timer.prompt_tokens == 150
        assert tracker.timer.completion_tokens == 8

    def test_mark_speech_end_resets_usage_for_the_new_turn(self):
        tracker = TurnTracker()
        tracker.mark_usage({"prompt_tokens": 100, "completion_tokens": 5})

        tracker.mark_speech_end(200.0)

        assert tracker.timer.prompt_tokens is None
        assert tracker.timer.completion_tokens is None


class TestPercentile:
    def test_single_value(self):
        assert percentile([42.0], 50) == 42.0

    def test_p50_of_an_odd_length_list(self):
        assert percentile([10.0, 20.0, 30.0], 50) == 20.0

    def test_p95_of_a_larger_list(self):
        values = [float(i) for i in range(1, 101)]  # 1..100
        assert percentile(values, 95) == 95.0

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            percentile([], 50)


class TestLoadTurns:
    def test_parses_valid_turn_lines(self, tmp_path):
        log_path = tmp_path / "turns.jsonl"
        log_path.write_text(
            '{"total_latency_ms": 1200.0, "session_id": "a"}\n'
            '{"total_latency_ms": 1500.0, "session_id": "b"}\n',
            encoding="utf-8",
        )

        turns = load_turns(log_path)

        assert len(turns) == 2
        assert turns[0]["session_id"] == "a"

    def test_skips_non_json_lines(self, tmp_path):
        """Other app log lines (e.g. "Caller connected") share the same file
        sink as turn metrics — only valid JSON turn records should count."""
        log_path = tmp_path / "turns.jsonl"
        log_path.write_text(
            'Caller connected\n{"total_latency_ms": 1200.0}\nCaller disconnected\n',
            encoding="utf-8",
        )

        turns = load_turns(log_path)

        assert len(turns) == 1

    def test_skips_json_lines_without_total_latency_ms(self, tmp_path):
        """A turn that never reached TTS (e.g. a tool error) still logs
        partial timestamps — it shouldn't be counted as a completed turn."""
        log_path = tmp_path / "turns.jsonl"
        log_path.write_text(
            '{"speech_end": 100.0}\n{"total_latency_ms": 900.0}\n',
            encoding="utf-8",
        )

        turns = load_turns(log_path)

        assert len(turns) == 1


class TestLatencySummary:
    def test_computes_p50_and_p95_per_stage(self):
        turns = [
            {"stt_latency_ms": 100.0, "total_latency_ms": 1000.0},
            {"stt_latency_ms": 200.0, "total_latency_ms": 2000.0},
            {"stt_latency_ms": 300.0, "total_latency_ms": 3000.0},
        ]

        summary = latency_summary(turns)

        assert summary["stt_latency_ms"]["p50"] == 200.0
        assert summary["stt_latency_ms"]["n"] == 3
        assert summary["total_latency_ms"]["p50"] == 2000.0

    def test_omits_a_stage_absent_from_every_turn(self):
        turns = [{"total_latency_ms": 1000.0}]

        summary = latency_summary(turns)

        assert "tts_latency_ms" not in summary

    def test_empty_turns_is_an_empty_summary(self):
        assert latency_summary([]) == {}

    def test_negative_duration_is_dropped_not_counted(self):
        """A negative duration is physically impossible — a symptom of
        TurnTracker's known overlapping-turns limitation (see
        docs/BUILD_PLAN.md phase 4 notes), not a real measurement. It must
        not skew the percentiles of the turns that *are* legitimate."""
        turns = [
            {"llm_latency_ms": 100.0, "total_latency_ms": 1000.0},
            {"llm_latency_ms": -60.0, "total_latency_ms": 1000.0},
            {"llm_latency_ms": 200.0, "total_latency_ms": 1000.0},
        ]

        summary = latency_summary(turns)

        assert summary["llm_latency_ms"]["n"] == 2
        assert summary["llm_latency_ms"]["dropped"] == 1
        assert summary["llm_latency_ms"]["p50"] == 100.0

    def test_dropped_is_zero_when_nothing_is_negative(self):
        summary = latency_summary([{"total_latency_ms": 1000.0}])

        assert summary["total_latency_ms"]["dropped"] == 0

    def test_all_negative_omits_the_stage_entirely(self):
        summary = latency_summary([{"llm_latency_ms": -10.0}])

        assert "llm_latency_ms" not in summary


class TestConfigureFileSink:
    def test_logged_turns_are_persisted_as_parseable_jsonl(self, tmp_path):
        log_path = tmp_path / "nested" / "turns.jsonl"
        other_sink = tmp_path / "other.log"
        other_sink_id = logger.add(other_sink)  # proves cleanup is scoped, not logger.remove(None)
        sink_id = configure_file_sink(log_path)
        assert isinstance(sink_id, int)
        try:
            timer = TurnTimer(
                speech_end=1.0, stt_final=1.2, llm_first_token=1.5, tts_first_audio=1.8
            )
            log_turn(timer, session_id="call-1")
        finally:
            logger.remove(sink_id)

        logger.info("after cleanup")
        logger.remove(other_sink_id)

        turns = load_turns(log_path)
        assert len(turns) == 1
        assert turns[0]["session_id"] == "call-1"
        assert "after cleanup" in other_sink.read_text(encoding="utf-8")


class TestEnsureFileSink:
    def test_second_call_does_not_duplicate_the_sink(self, tmp_path, monkeypatch):
        """Regression test: pipecat's dev runner (`pipecat.runner.run.main`)
        calls `logger.remove()` at server startup, wiping any sink added
        before it — so the real sink has to be added lazily, from inside
        the per-call entry point (`app.voice_bot.run_bot`), guarded so N
        calls in one process don't add N duplicate sinks (which would log
        every turn N times)."""
        monkeypatch.setattr(metrics, "_file_sink_configured", False)
        log_path = tmp_path / "turns.jsonl"

        ensure_file_sink(log_path)
        ensure_file_sink(log_path)
        timer = TurnTimer(speech_end=1.0, stt_final=1.1, llm_first_token=1.3, tts_first_audio=1.5)
        log_turn(timer, session_id="x")

        turns = load_turns(log_path)
        assert len(turns) == 1


class TestRenderLatencyReport:
    def test_includes_stage_names_and_percentiles(self):
        summary = {"total_latency_ms": {"p50": 1200.0, "p95": 2500.0, "n": 5, "dropped": 0}}

        report = render_latency_report(summary)

        assert "total_latency_ms" in report
        assert "1200" in report
        assert "2500" in report

    def test_includes_dropped_count(self):
        summary = {"llm_latency_ms": {"p50": 100.0, "p95": 200.0, "n": 2, "dropped": 1}}

        report = render_latency_report(summary)

        row = next(line for line in report.splitlines() if "llm_latency_ms" in line)
        assert row == "| llm_latency_ms | 2 | 100 | 200 | 1 |"

    def test_title_can_be_overridden(self):
        report = render_latency_report({}, title="Phase 4 latency report")

        assert report.startswith("# Phase 4 latency report")
