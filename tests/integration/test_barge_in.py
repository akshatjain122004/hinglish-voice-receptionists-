"""BUILD_PLAN 5.2 - barge-in: when the caller starts speaking, TTS stops
immediately, but a tool call already decided on (e.g. a booking) is never
cancelled halfway, and nothing from an interrupted turn leaks into the next
one.

`BargeInProcessor` and `AgentProcessor`'s interruption handling are the only
new code under test here - Pipecat's own `TTSService._handle_interruption()`
(which actually stops audio/drops queued output on an `InterruptionFrame`) is
exercised and owned by Pipecat itself, not re-tested here.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from pipecat.frames.frames import (
    InterruptionFrame,
    LLMFullResponseEndFrame,
    TextFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.tests.utils import SleepFrame, run_test
from sqlmodel import Session, select

from app import db as db_module
from app.agent import Agent
from app.booking import IST
from app.llm_streaming import ChatDelta, ToolCallDelta
from app.voice_bot import AgentProcessor, BargeInProcessor

NOW = datetime(2026, 11, 9, 10, 0, tzinfo=IST)


@pytest.mark.asyncio
async def test_barge_in_processor_broadcasts_interruption_on_vad_user_started():
    processor = BargeInProcessor()

    down_frames, up_frames = await run_test(
        processor,
        frames_to_send=[VADUserStartedSpeakingFrame()],
    )

    assert any(isinstance(f, InterruptionFrame) for f in down_frames)
    assert any(isinstance(f, InterruptionFrame) for f in up_frames)
    # The triggering frame is still forwarded - BargeInProcessor adds a
    # broadcast, it doesn't swallow anything.
    assert any(isinstance(f, VADUserStartedSpeakingFrame) for f in down_frames)


class _SlowSecondRoundLLM:
    """Round 1 decides a tool call instantly, like a real provider's first
    streamed delta. Round 2 (the confirmation reply, only ever asked for
    *after* the tool already ran) has a real `asyncio.sleep` before it -
    long enough that a concurrently-queued `InterruptionFrame` is guaranteed
    to already have been processed by `AgentProcessor` by the time round 2's
    content is generated. This is what makes the ordering in
    `test_caller_interrupts_mid_turn_does_not_lose_the_booking` deterministic
    instead of racy."""

    def __init__(self, tool_name: str, tool_arguments: dict) -> None:
        self._tool_name = tool_name
        self._tool_arguments = tool_arguments
        self.calls: list[dict] = []

    async def stream_chat(
        self, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[ChatDelta]:
        self.calls.append({"messages": [dict(m) for m in messages]})
        if len(self.calls) == 1:
            yield ChatDelta(
                tool_call_deltas=[
                    ToolCallDelta(
                        index=0,
                        id="1",
                        name=self._tool_name,
                        arguments_fragment=json.dumps(self._tool_arguments),
                    )
                ]
            )
            return
        await asyncio.sleep(0.05)
        yield ChatDelta(content="Aapki cleaning confirm ho gayi, Ravi.")


@pytest.mark.asyncio
async def test_caller_interrupts_mid_turn_does_not_lose_the_booking(db):
    llm = _SlowSecondRoundLLM(
        "book_appointment",
        {"name": "Ravi", "service": "cleaning", "start": "kal shaam saade paanch"},
    )
    agent = Agent(llm, now=NOW, caller_phone="9829012345")
    processor = AgentProcessor(agent, session_id="voice-call")

    down_frames, _ = await run_test(
        processor,
        frames_to_send=[
            TranscriptionFrame(
                text="Kal shaam cleaning book kar do",
                user_id="caller",
                timestamp="2026-11-09T10:00:00Z",
            ),
            # Give AgentProcessor time to start the turn (resetting
            # `_interrupted`), run round 1 (the tool call) and reach round 2's
            # real `asyncio.sleep` in `_SlowSecondRoundLLM`, so this
            # InterruptionFrame genuinely lands *mid-turn* rather than being
            # processed - and immediately reset away - before the turn even
            # starts.
            SleepFrame(sleep=0.02),
            InterruptionFrame(),
        ],
    )

    # The booking tool call ran and committed, even though the caller
    # interrupted before the agent's confirmation reply was ready.
    with Session(db_module.engine) as session:
        appointments = session.exec(select(db_module.Appointment)).all()
    assert len(appointments) == 1
    assert appointments[0].phone == "+919829012345"

    # handle_turn() was not cancelled: it went on to ask for (and get) the
    # round-2 confirmation reply, and that request's own history already
    # carries the tool's result.
    assert len(llm.calls) == 2
    assert any(m["role"] == "tool" for m in llm.calls[1]["messages"])

    # But the confirmation reply was never pushed as a TextFrame for TTS to
    # speak, since the caller had already started talking again by the time
    # it was ready (BUILD_PLAN 5.2's documented decision: history/transcript
    # keep the full reply even if the caller only heard part of the turn -
    # see docs/architecture.md).
    text_frames = [f for f in down_frames if isinstance(f, TextFrame)]
    assert text_frames == []
    assert any(isinstance(f, LLMFullResponseEndFrame) for f in down_frames)


class _InterruptThenReplyLLM:
    """First turn: a real delay before replying, so it's reliably still
    in-flight when the test fires an InterruptionFrame at it. Second turn:
    replies immediately, with different content - used to prove nothing
    from the first (interrupted) turn leaks into it."""

    def __init__(self) -> None:
        self.calls = 0

    async def stream_chat(
        self, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[ChatDelta]:
        self.calls += 1
        if self.calls == 1:
            await asyncio.sleep(0.05)
            yield ChatDelta(content="purani baat jo suni nahi jaani chahiye")
        else:
            yield ChatDelta(content="Namaste! Kaise madad kar sakti hoon?")


@pytest.mark.asyncio
async def test_next_turn_after_an_interruption_starts_clean():
    agent = Agent(_InterruptThenReplyLLM(), now=NOW)

    interrupted_down_frames, _ = await run_test(
        AgentProcessor(agent, session_id="voice-call"),
        frames_to_send=[
            TranscriptionFrame(
                text="kal slot hai?", user_id="caller", timestamp="2026-11-09T10:00:00Z"
            ),
            SleepFrame(sleep=0.02),
            InterruptionFrame(),
        ],
    )
    assert [f for f in interrupted_down_frames if isinstance(f, TextFrame)] == []

    next_turn_down_frames, _ = await run_test(
        AgentProcessor(agent, session_id="voice-call"),
        frames_to_send=[
            TranscriptionFrame(text="Namaste", user_id="caller", timestamp="2026-11-09T10:00:05Z")
        ],
    )
    text_frames = [f for f in next_turn_down_frames if isinstance(f, TextFrame)]
    assert [f.text for f in text_frames] == ["Namaste! Kaise madad kar sakti hoon?"]
