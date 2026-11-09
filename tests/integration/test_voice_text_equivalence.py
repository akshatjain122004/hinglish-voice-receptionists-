"""Feeds text frames into `AgentProcessor` (bypassing STT) and checks that it
produces exactly the tool calls the Phase 2 text agent (`Agent.handle_turn`)
produces for the same input — the voice pipeline must reuse that loop, not
reimplement tool-calling inside Pipecat."""

from datetime import datetime

import pytest
from pipecat.frames.frames import (
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.tests.utils import run_test

from app.agent import Agent, LLMResponse, ToolCall
from app.booking import IST
from app.voice_bot import AgentProcessor
from tests.fixtures.fake_llm import FakeLLM

NOW = datetime(2026, 11, 9, 10, 0, tzinfo=IST)


def _scripted_responses() -> list[LLMResponse]:
    return [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="1",
                    name="check_slots",
                    arguments={"date": "kal", "service": "cleaning", "part_of_day": "evening"},
                )
            ],
        ),
        LLMResponse(content="Kal shaam saade paanch aur chhe baje free hai, kaunsa chahiye?"),
    ]


@pytest.mark.asyncio
async def test_voice_frame_produces_same_tool_call_as_text_agent():
    text_agent = Agent(FakeLLM(responses=_scripted_responses()), now=NOW, caller_phone="9829012345")
    expected_reply = await text_agent.handle_turn(
        "text-call", "Kal shaam ko cleaning ka slot milega?"
    )

    seen_tool_calls: list[tuple[str, dict]] = []
    voice_agent = Agent(
        FakeLLM(responses=_scripted_responses()), now=NOW, caller_phone="9829012345"
    )
    processor = AgentProcessor(
        voice_agent,
        session_id="voice-call",
        on_tool_call=lambda name, arguments, result: seen_tool_calls.append((name, arguments)),
    )

    down_frames, _ = await run_test(
        processor,
        frames_to_send=[
            TranscriptionFrame(
                text="Kal shaam ko cleaning ka slot milega?",
                user_id="caller",
                timestamp="2026-11-09T10:00:00Z",
            )
        ],
    )

    assert seen_tool_calls == [
        ("check_slots", {"date": "kal", "service": "cleaning", "part_of_day": "evening"})
    ]

    text_frames = [f for f in down_frames if isinstance(f, TextFrame)]
    assert len(text_frames) == 1
    assert text_frames[0].text == expected_reply

    assert any(isinstance(f, LLMFullResponseStartFrame) for f in down_frames)
    assert any(isinstance(f, LLMFullResponseEndFrame) for f in down_frames)
