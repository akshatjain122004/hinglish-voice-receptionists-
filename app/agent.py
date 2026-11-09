"""The tool-calling loop, behind an LLM-agnostic interface.

This module never talks to a provider SDK directly. It only knows the
`LLMClient` protocol, so tests can plug in a scripted `FakeLLM` and a real
client (Sarvam) can be swapped in later without touching this file.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import httpx
from loguru import logger

from app import prompts, tools
from app.llm_streaming import ChatDelta, ToolCallAccumulator, ToolCallDelta

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
    def stream_chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[ChatDelta]: ...


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
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def stream_chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[ChatDelta]:
        async with (
            httpx.AsyncClient(timeout=self._timeout) as client,
            client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "api-subscription-key": self._api_key,
                },
                json={
                    "model": self._model,
                    "messages": messages,
                    "tools": tools,
                    "stream": True,
                },
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                delta = self._parse_sse_line(line)
                if delta is not None:
                    yield delta

    @staticmethod
    def _parse_sse_line(line: str) -> ChatDelta | None:
        if not line.startswith("data: "):
            return None
        payload = line[len("data: ") :].strip()
        if payload == "[DONE]":
            return None
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            logger.debug(f"Skipping malformed SSE line from Sarvam: {line!r}")
            return None

        choices = chunk.get("choices") or []
        if not choices:
            # Sarvam's documented stream_options.include_usage trailer chunk
            # has an empty choices array - nothing to extract from it.
            return None

        delta_obj = choices[0].get("delta") or {}
        tool_call_deltas = [
            ToolCallDelta(
                index=tc["index"],
                id=tc.get("id"),
                name=(tc.get("function") or {}).get("name"),
                arguments_fragment=(tc.get("function") or {}).get("arguments") or "",
            )
            for tc in delta_obj.get("tool_calls") or []
        ]
        return ChatDelta(content=delta_obj.get("content"), tool_call_deltas=tool_call_deltas)


class Agent:
    """Runs the tool-calling loop and keeps conversation history per session."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        now: datetime | None = None,
        system_prompt: str | None = None,
        caller_phone: str | None = None,
    ) -> None:
        self.llm = llm
        self.max_tool_rounds = max_tool_rounds
        self.now = now
        self.system_prompt = system_prompt or prompts.SYSTEM_PROMPT
        self.caller_phone = caller_phone
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
        on_reply_chunk: Callable[[str], Awaitable[None]] | None = None,
        caller_phone: str | None = None,
    ) -> str:
        caller_phone = caller_phone if caller_phone is not None else self.caller_phone
        history = self._history(session_id)
        history.append({"role": "user", "content": user_text})

        for _ in range(self.max_tool_rounds):
            accumulator = ToolCallAccumulator()
            content_buffer = ""
            saw_tool_call_delta = False

            async for delta in self.llm.stream_chat(history, tools.TOOL_SCHEMAS):
                if delta.tool_call_deltas:
                    saw_tool_call_delta = True
                    for tool_call_delta in delta.tool_call_deltas:
                        accumulator.add(tool_call_delta)
                if delta.content:
                    content_buffer += delta.content
                    if on_reply_chunk is not None and not saw_tool_call_delta:
                        await on_reply_chunk(delta.content)

            tool_calls = [
                ToolCall(id=f.id, name=f.name, arguments=f.arguments) for f in accumulator.finish()
            ]

            if not tool_calls:
                reply = content_buffer
                history.append({"role": "assistant", "content": reply})
                return reply

            history.append(
                {
                    "role": "assistant",
                    "content": content_buffer or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in tool_calls
                    ],
                }
            )
            for tc in tool_calls:
                result = tools.call_tool(
                    tc.name, tc.arguments, now=self.now, caller_phone=caller_phone
                )
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
