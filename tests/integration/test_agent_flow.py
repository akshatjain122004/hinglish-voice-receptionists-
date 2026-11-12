from datetime import datetime, timedelta

import pytest

from app.agent import (
    FALLBACK_MESSAGE,
    FALLBACK_MESSAGE_EN,
    Agent,
    LLMResponse,
    ToolCall,
    fallback_message,
)
from app.booking import IST, book, find_by_phone, get_free_slots
from app.llm_streaming import ChatDelta, ToolCallDelta
from tests.fixtures.fake_llm import FakeLLM

NOW = datetime(2026, 11, 9, 10, 0, tzinfo=IST)


@pytest.mark.asyncio
async def test_booking_flow_creates_exactly_one_appointment(db):
    fake = FakeLLM(
        responses=[
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
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="book_appointment",
                        arguments={
                            "name": "Ravi",
                            "service": "cleaning",
                            "start": "kal shaam saade paanch",
                        },
                    )
                ],
            ),
            LLMResponse(
                content="Aapka cleaning appointment kal shaam saade paanch baje confirm ho gaya hai."
            ),
        ]
    )
    agent = Agent(fake, now=NOW, caller_phone="9829012345")

    reply1 = await agent.handle_turn("call-1", "Kal shaam ko cleaning ka slot milega?")
    assert "saade paanch" in reply1.lower()

    reply2 = await agent.handle_turn(
        "call-1", "Saade paanch theek hai, naam Ravi hai, confirm kar do."
    )
    assert "confirm" in reply2.lower()

    assert len(find_by_phone("9829012345")) == 1


@pytest.mark.asyncio
async def test_slot_taken_error_lets_the_llm_offer_a_real_alternative(db):
    # 17:30 is already booked, so Ravi's attempt at the same time must fail
    # and the agent must keep going instead of crashing the loop.
    tomorrow = NOW.date() + timedelta(days=1)
    taken_slot = next(
        s
        for s in get_free_slots(tomorrow, "cleaning", "evening")
        if s.hour == 17 and s.minute == 30
    )
    book("9800000000", "Existing Patient", "cleaning", taken_slot, now=NOW)

    fake = FakeLLM(
        responses=[
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="book_appointment",
                        arguments={
                            "name": "Ravi",
                            "service": "cleaning",
                            "start": "kal shaam saade paanch",
                        },
                    )
                ],
            ),
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="check_slots",
                        arguments={"date": "kal", "service": "cleaning", "part_of_day": "evening"},
                    )
                ],
            ),
            LLMResponse(
                content="Woh slot book ho chuka hai, lekin kal chhe baje free hai, chahiye?"
            ),
        ]
    )
    agent = Agent(fake, now=NOW, caller_phone="9829012345")

    reply = await agent.handle_turn("call-2", "Kal shaam saade paanch book kar do, naam Ravi hai.")

    assert "chhe baje" in reply.lower()
    assert len(find_by_phone("9829012345")) == 0
    assert len(find_by_phone("9800000000")) == 1


@pytest.mark.asyncio
async def test_stops_after_max_tool_rounds_without_an_infinite_loop(db):
    def endless_check_slots(call_id: str) -> LLMResponse:
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id=call_id, name="check_slots", arguments={"date": "kal", "service": "cleaning"}
                )
            ],
        )

    fake = FakeLLM(responses=[endless_check_slots(str(i)) for i in range(4)])
    agent = Agent(fake, now=NOW, max_tool_rounds=4)

    reply = await agent.handle_turn("call-3", "mujhe appointment chahiye")

    assert reply == FALLBACK_MESSAGE
    assert len(fake.calls) == 4


@pytest.mark.asyncio
async def test_max_tool_rounds_fallback_matches_english_caller(db):
    """BUILD_PLAN 5.10's Phase 5 manual-call finding: this fallback used to
    be a fixed Hinglish phrase regardless of caller language."""

    def endless_check_slots(call_id: str) -> LLMResponse:
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id=call_id, name="check_slots", arguments={"date": "kal", "service": "cleaning"}
                )
            ],
        )

    fake = FakeLLM(responses=[endless_check_slots(str(i)) for i in range(4)])
    agent = Agent(fake, now=NOW, max_tool_rounds=4)

    reply = await agent.handle_turn("call-3", "I need an appointment")

    assert reply == FALLBACK_MESSAGE_EN


class TestFallbackMessage:
    def test_hindi_or_hinglish_input_gets_the_hindi_phrase(self):
        assert fallback_message("hi") == FALLBACK_MESSAGE

    def test_english_input_gets_the_english_phrase(self):
        assert fallback_message("en") == FALLBACK_MESSAGE_EN


@pytest.mark.asyncio
async def test_on_tool_call_hook_receives_name_arguments_and_result(db):
    fake = FakeLLM(
        responses=[
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="check_slots",
                        arguments={"date": "kal", "service": "cleaning"},
                    )
                ],
            ),
            LLMResponse(content="Kal yeh slots free hain."),
        ]
    )
    agent = Agent(fake, now=NOW)
    seen: list[tuple[str, dict, dict]] = []

    await agent.handle_turn(
        "call-4",
        "kal slot hai?",
        on_tool_call=lambda name, arguments, result: seen.append((name, arguments, result)),
    )

    assert len(seen) == 1
    name, arguments, result = seen[0]
    assert name == "check_slots"
    assert arguments == {"date": "kal", "service": "cleaning"}
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_assistant_tool_call_history_matches_openai_schema(db):
    """Sarvam's OpenAI-compatible API rejects a malformed `tool_calls` entry
    on the *next* request. FakeLLM doesn't validate this, so this test
    inspects the message history directly instead of relying on FakeLLM to
    reject a bad shape."""
    fake = FakeLLM(
        responses=[
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="check_slots",
                        arguments={"date": "kal", "service": "cleaning"},
                    )
                ],
            ),
            LLMResponse(content="Kal yeh slots free hain."),
        ]
    )
    agent = Agent(fake, now=NOW)

    await agent.handle_turn("call-5", "kal slot hai?")

    second_call_messages = fake.calls[1]["messages"]
    assistant_message = next(m for m in second_call_messages if m["role"] == "assistant")
    tool_call = assistant_message["tool_calls"][0]

    assert tool_call["id"] == "call_1"
    assert tool_call["type"] == "function"
    assert tool_call["function"]["name"] == "check_slots"
    assert tool_call["function"]["arguments"] == '{"date": "kal", "service": "cleaning"}'


@pytest.mark.asyncio
async def test_on_reply_chunk_fires_once_per_content_chunk_in_order(db):
    fake = FakeLLM(
        responses=[[ChatDelta(content="Kal saade paanch "), ChatDelta(content="baje free hai.")]]
    )
    agent = Agent(fake, now=NOW)
    seen: list[str] = []

    async def on_reply_chunk(chunk: str) -> None:
        seen.append(chunk)

    reply = await agent.handle_turn("call-6", "kal slot hai?", on_reply_chunk=on_reply_chunk)

    assert seen == ["Kal saade paanch ", "baje free hai."]
    assert reply == "Kal saade paanch baje free hai."


@pytest.mark.asyncio
async def test_on_reply_chunk_is_suppressed_once_a_tool_call_delta_is_seen(db):
    """Safety gate: once a round has shown even one tool-call delta, no more
    content from that round is ever forwarded to on_reply_chunk, even if a
    (hypothetical) content delta arrives afterward in the same round."""
    fake = FakeLLM(
        responses=[
            [
                ChatDelta(
                    tool_call_deltas=[
                        ToolCallDelta(
                            index=0,
                            id="1",
                            name="check_slots",
                            arguments_fragment='{"date": "kal", "service": "cleaning"}',
                        )
                    ]
                ),
                ChatDelta(content="this must never be spoken"),
            ],
            LLMResponse(content="Kal yeh slots free hain."),
        ]
    )
    agent = Agent(fake, now=NOW)
    seen: list[str] = []

    async def on_reply_chunk(chunk: str) -> None:
        seen.append(chunk)

    reply = await agent.handle_turn("call-7", "kal slot hai?", on_reply_chunk=on_reply_chunk)

    assert seen == ["Kal yeh slots free hain."]
    assert reply == "Kal yeh slots free hain."


@pytest.mark.asyncio
async def test_on_usage_fires_with_the_final_rounds_usage():
    """BUILD_PLAN 5.7a: each round's stream_chat() ends with its own usage
    chunk (merged here as a plain ChatDelta - see test_sarvam_llm_client.py
    for the real parsing); a turn with more than one round should report the
    *last* round's usage, since that's the generation llm_first_token
    actually timed."""
    fake = FakeLLM(
        responses=[
            [
                ChatDelta(
                    tool_call_deltas=[
                        ToolCallDelta(
                            index=0,
                            id="call_1",
                            name="check_slots",
                            arguments_fragment='{"date": "kal", "service": "cleaning"}',
                        )
                    ]
                ),
                ChatDelta(usage={"prompt_tokens": 100, "completion_tokens": 5}),
            ],
            [
                ChatDelta(content="Kal yeh slots free hain."),
                ChatDelta(usage={"prompt_tokens": 150, "completion_tokens": 8}),
            ],
        ]
    )
    agent = Agent(fake, now=NOW)
    seen: list[dict] = []

    reply = await agent.handle_turn("call-8", "kal slot hai?", on_usage=seen.append)

    assert seen == [
        {"prompt_tokens": 100, "completion_tokens": 5},
        {"prompt_tokens": 150, "completion_tokens": 8},
    ]
    assert reply == "Kal yeh slots free hain."
