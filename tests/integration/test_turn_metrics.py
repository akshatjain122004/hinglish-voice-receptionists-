"""`AgentProcessor` marks speech_end/stt_final/llm_first_token on a shared
`TurnTracker` as a turn moves through it, and `TTSLatencyMarker` marks
tts_first_audio (and logs the turn) on the first TTS audio frame after it."""

from datetime import datetime

import pytest
from pipecat.frames.frames import (
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.tests.utils import run_test

from app.agent import Agent, LLMResponse
from app.booking import IST
from app.llm_streaming import ChatDelta
from app.metrics import TurnTracker
from app.voice_bot import AgentProcessor, TTSLatencyMarker
from tests.fixtures.fake_llm import FakeLLM

NOW = datetime(2026, 11, 9, 10, 0, tzinfo=IST)


@pytest.mark.asyncio
async def test_agent_processor_marks_speech_end_stt_final_and_llm_first_token():
    agent = Agent(FakeLLM(responses=[LLMResponse(content="Namaste!")]), now=NOW)
    tracker = TurnTracker()
    processor = AgentProcessor(agent, turn_tracker=tracker)

    await run_test(
        processor,
        frames_to_send=[
            VADUserStoppedSpeakingFrame(timestamp=100.0),
            TranscriptionFrame(text="Namaste", user_id="caller", timestamp="2026-11-09T10:00:00Z"),
        ],
    )

    assert tracker.timer.speech_end == 100.0
    assert tracker.timer.stt_final is not None
    assert tracker.timer.llm_first_token is not None
    assert tracker.timer.stt_final <= tracker.timer.llm_first_token
    assert tracker.timer.tts_first_audio is None


@pytest.mark.asyncio
async def test_tts_latency_marker_marks_only_the_first_audio_frame_per_utterance():
    tracker = TurnTracker()
    tracker.timer.speech_end = 100.0
    marker = TTSLatencyMarker(tracker, session_id="call-1")

    await run_test(
        marker,
        frames_to_send=[
            TTSStartedFrame(),
            TTSAudioRawFrame(audio=b"\x00\x00", sample_rate=24000, num_channels=1),
            TTSAudioRawFrame(audio=b"\x00\x00", sample_rate=24000, num_channels=1),
        ],
    )

    first_mark = tracker.timer.tts_first_audio
    assert first_mark is not None


@pytest.mark.asyncio
async def test_llm_first_token_marked_only_once_across_multiple_chunks():
    agent = Agent(
        FakeLLM(responses=[[ChatDelta(content="Ek "), ChatDelta(content="pal.")]]), now=NOW
    )
    tracker = TurnTracker()
    call_count = 0
    original_mark = tracker.mark_llm_first_token

    def counting_mark(now: float) -> None:
        nonlocal call_count
        call_count += 1
        original_mark(now)

    tracker.mark_llm_first_token = counting_mark
    processor = AgentProcessor(agent, turn_tracker=tracker)

    await run_test(
        processor,
        frames_to_send=[
            TranscriptionFrame(
                text="kal slot hai?", user_id="caller", timestamp="2026-11-09T10:00:00Z"
            )
        ],
    )

    assert call_count == 1
    assert tracker.timer.llm_first_token is not None


@pytest.mark.asyncio
async def test_agent_processor_marks_usage_on_the_turn_tracker():
    """BUILD_PLAN 5.7a: AgentProcessor wires Agent's on_usage into
    TurnTracker.mark_usage - the pure mechanism is covered in
    tests/unit/test_metrics.py and tests/integration/test_agent_flow.py,
    this is the pipeline wiring."""
    agent = Agent(
        FakeLLM(
            responses=[
                [
                    ChatDelta(content="Namaste!"),
                    ChatDelta(usage={"prompt_tokens": 77, "completion_tokens": 3}),
                ]
            ]
        ),
        now=NOW,
    )
    tracker = TurnTracker()
    processor = AgentProcessor(agent, turn_tracker=tracker)

    await run_test(
        processor,
        frames_to_send=[
            TranscriptionFrame(text="Namaste", user_id="caller", timestamp="2026-11-09T10:00:00Z")
        ],
    )

    assert tracker.timer.prompt_tokens == 77
    assert tracker.timer.completion_tokens == 3
