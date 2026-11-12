"""BUILD_PLAN 5.3 - silence handling: reprompt after ~5s of the caller not
saying anything, end the call after a second silent window, and never fire
while the bot is actually speaking or the agent is thinking/running a tool.

Uses a real but tiny `silence_timeout` (no fake clock) and Pipecat's own
`SleepFrame` test helper, the same timing approach already used for
`tests/integration/test_barge_in.py`.
"""

from __future__ import annotations

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.tests.utils import SleepFrame, run_test

from app.voice_bot import (
    SILENCE_GOODBYE_TEXT,
    SILENCE_GOODBYE_TEXT_EN,
    SILENCE_REPROMPT_TEXT,
    SILENCE_REPROMPT_TEXT_EN,
    SilenceProcessor,
)

TIMEOUT = 0.03
WAIT_PAST_TIMEOUT = SleepFrame(sleep=TIMEOUT * 3)
# LLMFullResponseStart/EndFrame are ControlFrames (go through the ordered
# per-processor queue), but BotStoppedSpeakingFrame is a SystemFrame
# (processed immediately by a separate input task, jumping ahead of anything
# still sitting in that queue). In a real call this never matters -
# BotStoppedSpeakingFrame only arrives once the actual TTS audio finishes
# playing, long after LLMFullResponseEndFrame was processed - but sending
# both back-to-back here, as these tests do, reproduces the jump: measured
# empirically, anything under ~100ms still raced in this test harness, so
# this uses a comfortable margin above that, not a tuned minimum.
LET_CONTROL_FRAMES_DRAIN = SleepFrame(sleep=0.15)


def _speak_frames(down_frames) -> list[str]:
    return [f.text for f in down_frames if isinstance(f, TTSSpeakFrame)]


@pytest.mark.asyncio
async def test_reprompt_after_silence_following_bot_speech():
    down_frames, _ = await run_test(
        SilenceProcessor(silence_timeout=TIMEOUT),
        frames_to_send=[
            LLMFullResponseStartFrame(),
            LLMFullResponseEndFrame(),
            LET_CONTROL_FRAMES_DRAIN,
            BotStoppedSpeakingFrame(),
            WAIT_PAST_TIMEOUT,
        ],
    )

    assert _speak_frames(down_frames) == [SILENCE_REPROMPT_TEXT]


@pytest.mark.asyncio
async def test_reprompt_matches_english_caller_via_lang_provider():
    """BUILD_PLAN 5.10's Phase 5 manual-call finding: the reprompt/goodbye
    used to be fixed Hinglish phrases regardless of caller language. No new
    caller text exists at the moment silence fires, so SilenceProcessor
    reads whatever lang_provider() returns right then, not a snapshot taken
    at construction time."""
    down_frames, _ = await run_test(
        SilenceProcessor(silence_timeout=TIMEOUT, lang_provider=lambda: "en"),
        frames_to_send=[
            LLMFullResponseStartFrame(),
            LLMFullResponseEndFrame(),
            LET_CONTROL_FRAMES_DRAIN,
            BotStoppedSpeakingFrame(),
            WAIT_PAST_TIMEOUT,
        ],
    )

    assert _speak_frames(down_frames) == [SILENCE_REPROMPT_TEXT_EN]


@pytest.mark.asyncio
async def test_second_silence_ends_the_call():
    end_call_invocations: list[None] = []

    async def end_call() -> None:
        end_call_invocations.append(None)

    down_frames, _ = await run_test(
        SilenceProcessor(silence_timeout=TIMEOUT, end_call=end_call),
        frames_to_send=[
            LLMFullResponseStartFrame(),
            LLMFullResponseEndFrame(),
            LET_CONTROL_FRAMES_DRAIN,
            BotStoppedSpeakingFrame(),
            WAIT_PAST_TIMEOUT,  # -> reprompt
            # The reprompt's own TTS output starting and finishing, exactly
            # like any other TTSSpeakFrame played by the real pipeline.
            BotStartedSpeakingFrame(),
            BotStoppedSpeakingFrame(),
            WAIT_PAST_TIMEOUT,  # -> goodbye + end_call()
        ],
    )

    assert _speak_frames(down_frames) == [SILENCE_REPROMPT_TEXT, SILENCE_GOODBYE_TEXT]
    assert len(end_call_invocations) == 1


@pytest.mark.asyncio
async def test_second_silence_goodbye_matches_english_caller_via_lang_provider():
    down_frames, _ = await run_test(
        SilenceProcessor(silence_timeout=TIMEOUT, lang_provider=lambda: "en"),
        frames_to_send=[
            LLMFullResponseStartFrame(),
            LLMFullResponseEndFrame(),
            LET_CONTROL_FRAMES_DRAIN,
            BotStoppedSpeakingFrame(),
            WAIT_PAST_TIMEOUT,  # -> reprompt
            BotStartedSpeakingFrame(),
            BotStoppedSpeakingFrame(),
            WAIT_PAST_TIMEOUT,  # -> goodbye
        ],
    )

    assert _speak_frames(down_frames) == [SILENCE_REPROMPT_TEXT_EN, SILENCE_GOODBYE_TEXT_EN]


@pytest.mark.asyncio
async def test_timer_does_not_fire_while_bot_is_speaking():
    down_frames, _ = await run_test(
        SilenceProcessor(silence_timeout=TIMEOUT),
        frames_to_send=[
            LLMFullResponseStartFrame(),
            LLMFullResponseEndFrame(),
            LET_CONTROL_FRAMES_DRAIN,
            BotStoppedSpeakingFrame(),
            # The bot starts talking again (e.g. a later TTS clip, or a
            # filler) before the window elapses - the timer must not have
            # fired in between.
            BotStartedSpeakingFrame(),
            WAIT_PAST_TIMEOUT,
        ],
    )

    assert _speak_frames(down_frames) == []


@pytest.mark.asyncio
async def test_timer_does_not_fire_while_the_agent_is_thinking_or_running_a_tool():
    """A slow `answer_faq` (or any tool) must never trigger the reprompt
    mid-answer. Modelled here as: the *previous* turn's BotStoppedSpeaking
    correctly arms the timer, but the *next* turn starts (LLMFullResponseStartFrame,
    pushed by AgentProcessor before it even calls Agent.handle_turn()) before
    that timer would have fired - which must cancel it, exactly as it would
    for a real slow tool call sitting inside that same turn."""
    down_frames, _ = await run_test(
        SilenceProcessor(silence_timeout=TIMEOUT),
        frames_to_send=[
            LLMFullResponseStartFrame(),
            LLMFullResponseEndFrame(),
            LET_CONTROL_FRAMES_DRAIN,
            BotStoppedSpeakingFrame(),  # previous turn ends, timer arms
            LLMFullResponseStartFrame(),  # next turn starts (e.g. a slow tool call)
            WAIT_PAST_TIMEOUT,
        ],
    )

    assert _speak_frames(down_frames) == []


@pytest.mark.asyncio
async def test_caller_speech_resets_the_timer():
    down_frames, _ = await run_test(
        SilenceProcessor(silence_timeout=TIMEOUT),
        frames_to_send=[
            LLMFullResponseStartFrame(),
            LLMFullResponseEndFrame(),
            LET_CONTROL_FRAMES_DRAIN,
            BotStoppedSpeakingFrame(),
            VADUserStartedSpeakingFrame(),
            WAIT_PAST_TIMEOUT,
        ],
    )

    assert _speak_frames(down_frames) == []
