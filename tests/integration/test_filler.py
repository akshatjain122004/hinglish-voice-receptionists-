"""BUILD_PLAN 5.4 - filler for slow tools: say a fixed phrase if a single
tool call runs past a threshold, so the caller doesn't hear dead air while
e.g. `answer_faq`'s embedding lookup runs. At most one filler per turn, even
if a turn has two slow tool rounds.

Uses a real but tiny `filler_threshold_secs` (no fake clock), and a
monkeypatched `app.tools.call_tool` that calls `time.sleep()` to model a
slow synchronous tool - exactly how a real one blocks (BUILD_PLAN 5.4's own
"check first": these run via `asyncio.to_thread` precisely so this kind of
blocking call doesn't freeze the event loop or the filler timer).
"""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from app import tools as tools_module
from app.agent import Agent, LLMResponse, ToolCall
from app.booking import IST
from tests.fixtures.fake_llm import FakeLLM

NOW = datetime(2026, 11, 9, 10, 0, tzinfo=IST)
THRESHOLD = 0.05


def _tool_call(call_id: str) -> LLMResponse:
    return LLMResponse(
        content=None, tool_calls=[ToolCall(id=call_id, name="check_slots", arguments={})]
    )


@pytest.mark.asyncio
async def test_slow_tool_fires_filler_before_the_answer(monkeypatch):
    monkeypatch.setattr(
        tools_module, "call_tool", lambda *a, **k: (time.sleep(0.15), {"ok": True})[1]
    )

    fired: list[str] = []

    async def on_slow_tool(lang: str) -> None:
        fired.append(lang)

    agent = Agent(
        FakeLLM(responses=[_tool_call("1"), LLMResponse(content="Yahan hai.")]),
        now=NOW,
        filler_threshold_secs=THRESHOLD,
    )
    reply = await agent.handle_turn("call-1", "kal slot hai?", on_slow_tool=on_slow_tool)

    assert fired == ["hi"]
    assert reply == "Yahan hai."


@pytest.mark.asyncio
async def test_fast_tool_produces_no_filler(monkeypatch):
    monkeypatch.setattr(tools_module, "call_tool", lambda *a, **k: {"ok": True})

    fired: list[str] = []

    async def on_slow_tool(lang: str) -> None:
        fired.append(lang)

    agent = Agent(
        FakeLLM(responses=[_tool_call("1"), LLMResponse(content="Yahan hai.")]),
        now=NOW,
        filler_threshold_secs=THRESHOLD,
    )
    reply = await agent.handle_turn("call-1", "kal slot hai?", on_slow_tool=on_slow_tool)

    assert fired == []
    assert reply == "Yahan hai."


@pytest.mark.asyncio
async def test_slow_tool_filler_matches_english_caller(monkeypatch):
    """BUILD_PLAN 5.10's Phase 5 manual-call finding: the filler used to be a
    fixed Hinglish phrase regardless of caller language."""
    monkeypatch.setattr(
        tools_module, "call_tool", lambda *a, **k: (time.sleep(0.15), {"ok": True})[1]
    )

    fired: list[str] = []

    async def on_slow_tool(lang: str) -> None:
        fired.append(lang)

    agent = Agent(
        FakeLLM(responses=[_tool_call("1"), LLMResponse(content="It's free.")]),
        now=NOW,
        filler_threshold_secs=THRESHOLD,
    )
    reply = await agent.handle_turn(
        "call-1", "Is there a slot tomorrow?", on_slow_tool=on_slow_tool
    )

    assert fired == ["en"]
    assert reply == "It's free."


@pytest.mark.asyncio
async def test_two_slow_rounds_in_one_turn_still_fire_only_one_filler(monkeypatch):
    monkeypatch.setattr(
        tools_module, "call_tool", lambda *a, **k: (time.sleep(0.15), {"ok": True})[1]
    )

    fired: list[str] = []

    async def on_slow_tool(lang: str) -> None:
        fired.append(lang)

    agent = Agent(
        FakeLLM(
            responses=[
                _tool_call("1"),  # round 1: slow tool call
                _tool_call("2"),  # round 2: another slow tool call, same turn
                LLMResponse(content="Yahan hai."),
            ]
        ),
        now=NOW,
        filler_threshold_secs=THRESHOLD,
    )
    reply = await agent.handle_turn("call-1", "kal slot hai?", on_slow_tool=on_slow_tool)

    assert len(fired) == 1
    assert reply == "Yahan hai."


@pytest.mark.asyncio
async def test_no_on_slow_tool_callback_is_fine(monkeypatch):
    """Text callers (chat_cli.py) never pass on_slow_tool at all."""
    monkeypatch.setattr(
        tools_module, "call_tool", lambda *a, **k: (time.sleep(0.15), {"ok": True})[1]
    )

    agent = Agent(
        FakeLLM(responses=[_tool_call("1"), LLMResponse(content="Yahan hai.")]),
        now=NOW,
        filler_threshold_secs=THRESHOLD,
    )
    reply = await agent.handle_turn("call-1", "kal slot hai?")

    assert reply == "Yahan hai."
