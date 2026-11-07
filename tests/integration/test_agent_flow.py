from datetime import datetime, timedelta

import pytest

from app.agent import FALLBACK_MESSAGE, Agent, LLMResponse, ToolCall
from app.booking import IST, book, find_by_phone, get_free_slots
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
                            "phone": "9829012345",
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
    agent = Agent(fake, now=NOW)

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
                            "phone": "9829012345",
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
    agent = Agent(fake, now=NOW)

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
