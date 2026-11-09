"""Pure, provider-agnostic pieces of consuming a streamed chat completion.

No HTTP, no pipecat imports here - mirrors app/metrics.py's pattern of
staying trivially unit-testable without a real network client or the
frame-processing stack.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class ToolCallDelta:
    """One fragment of one tool call, as a provider streams it.

    OpenAI-compatible streaming APIs (Sarvam included) send a tool call's
    `id`/`name` once, in an early chunk, and its `arguments` as many small
    string fragments across later chunks - all tagged with the same
    `index` so a consumer can tell which fragments belong to which call.
    """

    index: int
    id: str | None = None
    name: str | None = None
    arguments_fragment: str = ""


@dataclass
class ChatDelta:
    """One chunk of a streamed chat completion."""

    content: str | None = None
    tool_call_deltas: list[ToolCallDelta] = field(default_factory=list)


@dataclass
class FinishedToolCall:
    """A tool call once all of its streamed fragments have been merged."""

    id: str
    name: str
    arguments: dict


class ToolCallAccumulator:
    """Merges a stream of `ToolCallDelta`s into finished `FinishedToolCall`s.

    Call `add()` for every delta seen in a round, in arrival order, then
    `finish()` once the stream ends.
    """

    def __init__(self) -> None:
        self._order: list[int] = []
        self._ids: dict[int, str] = {}
        self._names: dict[int, str] = {}
        self._arguments: dict[int, str] = {}

    def add(self, delta: ToolCallDelta) -> None:
        if delta.index not in self._arguments:
            self._order.append(delta.index)
            self._arguments[delta.index] = ""
        if delta.id is not None:
            self._ids[delta.index] = delta.id
        if delta.name is not None:
            self._names[delta.index] = delta.name
        self._arguments[delta.index] += delta.arguments_fragment

    def finish(self) -> list[FinishedToolCall]:
        return [
            FinishedToolCall(
                id=self._ids[index],
                name=self._names[index],
                arguments=json.loads(self._arguments[index]) if self._arguments[index] else {},
            )
            for index in self._order
        ]
