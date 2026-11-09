"""A scripted `LLMClient` test double — see `app.agent.LLMClient`."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.agent import LLMResponse
from app.llm_streaming import ChatDelta, ToolCallDelta


def _as_deltas(scripted: LLMResponse | list[ChatDelta]) -> list[ChatDelta]:
    """Wraps a scripted `LLMResponse` into the chunk(s) a real streaming
    client would have produced for it: one chunk for its content (if any),
    one chunk per tool call. A test that already wants fine control over
    chunk timing scripts a `list[ChatDelta]` directly instead."""
    if isinstance(scripted, list):
        return scripted

    deltas: list[ChatDelta] = []
    if scripted.content:
        deltas.append(ChatDelta(content=scripted.content))
    for index, tool_call in enumerate(scripted.tool_calls):
        deltas.append(
            ChatDelta(
                tool_call_deltas=[
                    ToolCallDelta(
                        index=index,
                        id=tool_call.id,
                        name=tool_call.name,
                        arguments_fragment=json.dumps(tool_call.arguments),
                    )
                ]
            )
        )
    return deltas


@dataclass
class FakeLLM:
    responses: list[LLMResponse | list[ChatDelta]]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def stream_chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[ChatDelta]:
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if not self.responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        for delta in _as_deltas(self.responses.pop(0)):
            yield delta
