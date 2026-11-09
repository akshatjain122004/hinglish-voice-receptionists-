"""Feeds text frames into `AgentProcessor` (bypassing STT) and checks that it
produces exactly the tool calls the Phase 2 text agent (`Agent.handle_turn`)
produces for the same input — the voice pipeline must reuse that loop, not
reimplement tool-calling inside Pipecat."""

from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from pipecat.frames.frames import (
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.tests.utils import run_test

from app.agent import FALLBACK_MESSAGE, Agent, LLMResponse, ToolCall
from app.booking import IST
from app.llm_streaming import ChatDelta
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
async def test_voice_frame_produces_same_tool_call_as_text_agent(db):
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


@pytest.mark.asyncio
async def test_on_turn_hook_receives_user_text_and_reply():
    agent = Agent(FakeLLM(responses=[LLMResponse(content="Namaste!")]), now=NOW)
    seen_turns: list[tuple[str, str]] = []
    processor = AgentProcessor(
        agent,
        session_id="voice-call",
        on_turn=lambda user_text, reply: seen_turns.append((user_text, reply)),
    )

    await run_test(
        processor,
        frames_to_send=[
            TranscriptionFrame(text="Namaste", user_id="caller", timestamp="2026-11-09T10:00:00Z")
        ],
    )

    assert seen_turns == [("Namaste", "Namaste!")]


@pytest.mark.asyncio
async def test_voice_frame_pushes_one_text_frame_per_reply_chunk():
    expected_reply = await Agent(
        FakeLLM(
            responses=[
                [ChatDelta(content="Kal saade paanch "), ChatDelta(content="baje free hai.")]
            ]
        ),
        now=NOW,
    ).handle_turn("text-call", "kal slot hai?")

    processor = AgentProcessor(
        Agent(
            FakeLLM(
                responses=[
                    [ChatDelta(content="Kal saade paanch "), ChatDelta(content="baje free hai.")]
                ]
            ),
            now=NOW,
        ),
        session_id="voice-call",
    )

    down_frames, _ = await run_test(
        processor,
        frames_to_send=[
            TranscriptionFrame(
                text="kal slot hai?", user_id="caller", timestamp="2026-11-09T10:00:00Z"
            )
        ],
    )

    text_frames = [f for f in down_frames if isinstance(f, TextFrame)]
    assert [f.text for f in text_frames] == ["Kal saade paanch ", "baje free hai."]
    assert "".join(f.text for f in text_frames) == expected_reply


@pytest.mark.asyncio
async def test_handle_turn_exception_mid_stream_falls_back_and_closes_turn():
    """Finding #1 (final-review): if `Agent.handle_turn()` raises partway through a
    streamed reply (Sarvam's HTTP call is known-flaky, e.g. `httpx.ReadTimeout` — see
    `_FlakyLLM` in tests/fixtures), `AgentProcessor` must still push
    `LLMFullResponseEndFrame` (so pipecat's TTS turn context closes and no leftover
    partial sentence bleeds into the next turn) and must still speak something: the
    content already streamed before the failure, followed by `FALLBACK_MESSAGE`."""

    class _FlakyMidStreamLLM:
        async def stream_chat(
            self, messages: list[dict], tools: list[dict]
        ) -> AsyncIterator[ChatDelta]:
            yield ChatDelta(content="Kal saade paanch ")
            raise RuntimeError("boom")

    agent = Agent(_FlakyMidStreamLLM(), now=NOW)
    processor = AgentProcessor(agent, session_id="voice-call")

    down_frames, _ = await run_test(
        processor,
        frames_to_send=[
            TranscriptionFrame(
                text="kal slot hai?", user_id="caller", timestamp="2026-11-09T10:00:00Z"
            )
        ],
    )

    text_frames = [f for f in down_frames if isinstance(f, TextFrame)]
    assert [f.text for f in text_frames] == ["Kal saade paanch ", FALLBACK_MESSAGE]

    end_frames = [f for f in down_frames if isinstance(f, LLMFullResponseEndFrame)]
    assert len(end_frames) == 1


@pytest.mark.asyncio
async def test_fallback_message_is_still_spoken_when_max_tool_rounds_hit(db):
    def endless_check_slots(call_id: str) -> LLMResponse:
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id=call_id,
                    name="check_slots",
                    arguments={"date": "kal", "service": "cleaning"},
                )
            ],
        )

    agent = Agent(
        FakeLLM(responses=[endless_check_slots(str(i)) for i in range(4)]),
        now=NOW,
        max_tool_rounds=4,
    )
    processor = AgentProcessor(agent, session_id="voice-call")

    down_frames, _ = await run_test(
        processor,
        frames_to_send=[
            TranscriptionFrame(
                text="mujhe appointment chahiye", user_id="caller", timestamp="2026-11-09T10:00:00Z"
            )
        ],
    )

    text_frames = [f for f in down_frames if isinstance(f, TextFrame)]
    assert len(text_frames) == 1
    assert text_frames[0].text == FALLBACK_MESSAGE
