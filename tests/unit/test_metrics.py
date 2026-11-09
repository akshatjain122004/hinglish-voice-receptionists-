import json

import pytest

from app.metrics import TurnTimer, turn_log_line


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
