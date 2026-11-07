"""The tool-calling loop, behind an LLM-agnostic interface.

This module never talks to a provider SDK directly. It only knows the
`LLMClient` protocol, so tests can plug in a scripted `FakeLLM` and a real
client (Sarvam) can be swapped in later without touching this file.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import httpx

from app import prompts, tools

MAX_TOOL_ROUNDS = 4

FALLBACK_MESSAGE = (
    "Maaf kijiye, thoda technical issue ho raha hai. "
    "Main staff se confirm karke aapko WhatsApp kar dungi."
)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse: ...


class SarvamLLMClient:
    """LLMClient backed by Sarvam's OpenAI-compatible chat completions API.

    Sarvam wants the key both as a normal Bearer token and as an
    `api-subscription-key` header (see pipecat's own SarvamLLMService).
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "sarvam-105b",
        base_url: str = "https://api.sarvam.ai/v2",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "api-subscription-key": self._api_key,
                },
                json={"model": self._model, "messages": messages, "tools": tools},
            )
            response.raise_for_status()
            return self._parse(response.json())

    @staticmethod
    def _parse(data: dict[str, Any]) -> LLMResponse:
        message = data["choices"][0]["message"]
        tool_calls = [
            ToolCall(
                id=call["id"],
                name=call["function"]["name"],
                arguments=json.loads(call["function"]["arguments"]),
            )
            for call in message.get("tool_calls") or []
        ]
        return LLMResponse(content=message.get("content"), tool_calls=tool_calls)


class Agent:
    """Runs the tool-calling loop and keeps conversation history per session."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        now: datetime | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.llm = llm
        self.max_tool_rounds = max_tool_rounds
        self.now = now
        self.system_prompt = system_prompt or prompts.SYSTEM_PROMPT
        self._sessions: dict[str, list[dict[str, Any]]] = {}

    def _history(self, session_id: str) -> list[dict[str, Any]]:
        return self._sessions.setdefault(
            session_id, [{"role": "system", "content": self.system_prompt}]
        )

    async def handle_turn(
        self,
        session_id: str,
        user_text: str,
        *,
        on_tool_call: Callable[[str, dict[str, Any], dict[str, Any]], None] | None = None,
    ) -> str:
        history = self._history(session_id)
        history.append({"role": "user", "content": user_text})

        for _ in range(self.max_tool_rounds):
            response = await self.llm.chat(history, tools.TOOL_SCHEMAS)

            if not response.tool_calls:
                reply = response.content or ""
                history.append({"role": "assistant", "content": reply})
                return reply

            history.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in response.tool_calls
                    ],
                }
            )
            for tc in response.tool_calls:
                result = tools.call_tool(tc.name, tc.arguments, now=self.now)
                if on_tool_call is not None:
                    on_tool_call(tc.name, tc.arguments, result)
                history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": json.dumps(result),
                    }
                )

        history.append({"role": "assistant", "content": FALLBACK_MESSAGE})
        return FALLBACK_MESSAGE
