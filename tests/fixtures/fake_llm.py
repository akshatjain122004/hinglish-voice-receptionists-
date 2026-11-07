"""A scripted `LLMClient` test double — see `app.agent.LLMClient`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agent import LLMResponse


@dataclass
class FakeLLM:
    responses: list[LLMResponse]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if not self.responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self.responses.pop(0)
