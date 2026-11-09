# Phase 5.1: Streaming LLM Tokens + Sentence-by-Sentence TTS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream Sarvam's chat-completion response token-by-token and forward it to TTS
incrementally, so the caller starts hearing sentence 1 while the LLM is still generating
sentence 2, instead of waiting for Phase 4's current ~2.6–5.6s (p50–p95) full-reply wait.

**Architecture:** A new pure module (`app/llm_streaming.py`) handles the provider-agnostic
bits of streaming (accumulating fragmented tool-call deltas). `app/agent.py`'s
`LLMClient` protocol moves from one blocking `chat()` call to an async-generator
`stream_chat()`; `Agent.handle_turn()` consumes that stream and gains one new optional
callback, `on_reply_chunk`, fired live with each content delta — but only once the
current round is confirmed tool-call-free, so nothing is ever spoken that might turn
out to be a dropped tool-call preamble. `app/voice_bot.py`'s `AgentProcessor` wires that
callback to push a `TextFrame` per chunk immediately; pipecat's `TTSService` already
buffers incoming text and dispatches synthesis per completed sentence
(`TextAggregationMode.SENTENCE`, the existing default), so no custom sentence-splitter
is needed anywhere in this project's code. The text path (`chat_cli.py`,
`scripts/run_evals.py`) never passes `on_reply_chunk`, so its behavior and
`handle_turn()`'s return value are unchanged.

**Tech Stack:** Python 3.11, httpx (async SSE via `AsyncClient.stream()`), existing
pipecat `TTSService`/`AgentProcessor`/`TurnTracker` machinery, pytest + respx for
offline-only tests (no live API calls needed to implement or verify this).

**Spec:** `docs/superpowers/specs/2026-11-09-voice-streaming-design.md`

## Global Constraints

- Offline test suite (`pytest`, no `-m live`) must stay green, free, and under ~30s
  total, per `CLAUDE.md`. No new paid API calls anywhere in this plan.
- No new dependencies. `httpx`, `respx`, `pytest-asyncio` are already in `pyproject.toml`.
- `Agent.handle_turn()`'s existing public contract (signature minus the one new
  optional kwarg, and its return value) must not change for any caller that doesn't
  pass `on_reply_chunk` — `scripts/chat_cli.py`, `scripts/run_evals.py`/`app/evals.py`
  pass none of the new kwargs and must need zero changes.
- Every existing test in `tests/integration/test_agent_flow.py`,
  `tests/integration/test_voice_text_equivalence.py`, and
  `tests/integration/test_turn_metrics.py` must keep passing unmodified (only new test
  functions are added to those files — no existing assertions change).
- A tool-calling round never speaks partial content once a tool-call delta has been
  seen in that round (the safety gate from the spec). A round that never produces a
  tool-call delta streams its content live.
- `TurnTracker.mark_llm_first_token` is a plain setter (overwrites on every call, not
  idempotent) — any code that calls it per-chunk must guard so only the first call per
  turn actually marks it.
- `Agent.handle_turn()`'s fallback path (hitting `max_tool_rounds`, returning
  `FALLBACK_MESSAGE`) never goes through `stream_chat()`/`on_reply_chunk` at all — the
  voice path must still push that message as a `TextFrame`, or the caller hears
  nothing. (This is a correctness fix this plan introduces, not something already
  covered by the spec's pseudocode — see Task 4.)

---

### Task 1: `app/llm_streaming.py` — pure streaming data types + tool-call accumulator

**Files:**
- Create: `app/llm_streaming.py`
- Create: `tests/unit/test_llm_streaming.py`

**Interfaces:**
- Produces: `ChatDelta(content: str | None = None, tool_call_deltas: list[ToolCallDelta] = [])`
  — dataclass, used by Task 2/3/4.
- Produces: `ToolCallDelta(index: int, id: str | None = None, name: str | None = None, arguments_fragment: str = "")`
  — dataclass, used by Task 2/3.
- Produces: `FinishedToolCall(id: str, name: str, arguments: dict)` — dataclass, used by Task 2.
- Produces: `ToolCallAccumulator` — class with `.add(delta: ToolCallDelta) -> None` and
  `.finish() -> list[FinishedToolCall]`, used by Task 2.

No HTTP, no pipecat imports in this file — it must stay trivially unit-testable with
synthetic data, mirroring `app/metrics.py`'s existing pattern.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_llm_streaming.py`:

```python
from app.llm_streaming import ChatDelta, ToolCallAccumulator, ToolCallDelta


def test_single_chunk_tool_call():
    acc = ToolCallAccumulator()
    acc.add(
        ToolCallDelta(
            index=0, id="call_1", name="check_slots", arguments_fragment='{"date": "kal"}'
        )
    )

    result = acc.finish()

    assert len(result) == 1
    assert result[0].id == "call_1"
    assert result[0].name == "check_slots"
    assert result[0].arguments == {"date": "kal"}


def test_fragmented_arguments_across_many_chunks():
    """OpenAI-compatible streaming sends `arguments` as many small string
    fragments across chunks, all needing concatenation before they parse as
    JSON. Only the first fragment for an index carries `id`/`name`."""
    acc = ToolCallAccumulator()
    acc.add(
        ToolCallDelta(index=0, id="call_1", name="book_appointment", arguments_fragment="")
    )
    acc.add(ToolCallDelta(index=0, arguments_fragment='{"name": '))
    acc.add(ToolCallDelta(index=0, arguments_fragment='"Ravi", '))
    acc.add(ToolCallDelta(index=0, arguments_fragment='"service": "cleaning"}'))

    result = acc.finish()

    assert len(result) == 1
    assert result[0].arguments == {"name": "Ravi", "service": "cleaning"}


def test_two_parallel_tool_calls_merge_by_index_not_arrival_order():
    acc = ToolCallAccumulator()
    acc.add(ToolCallDelta(index=0, id="call_1", name="check_slots", arguments_fragment='{"date"'))
    acc.add(
        ToolCallDelta(index=1, id="call_2", name="answer_faq", arguments_fragment='{"question"')
    )
    acc.add(ToolCallDelta(index=0, arguments_fragment=': "kal"}'))
    acc.add(ToolCallDelta(index=1, arguments_fragment=': "fees?"}'))

    result = acc.finish()

    assert [tc.name for tc in result] == ["check_slots", "answer_faq"]
    assert result[0].arguments == {"date": "kal"}
    assert result[1].arguments == {"question": "fees?"}


def test_no_tool_calls_returns_empty_list():
    acc = ToolCallAccumulator()

    assert acc.finish() == []


def test_chat_delta_defaults_to_no_tool_call_deltas():
    delta = ChatDelta(content="Namaste!")

    assert delta.tool_call_deltas == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_llm_streaming.py -v`
Expected: `ModuleNotFoundError: No module named 'app.llm_streaming'`

- [ ] **Step 3: Write the implementation**

Create `app/llm_streaming.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_llm_streaming.py -v`
Expected: 5 passed

- [ ] **Step 5: Lint and format**

Run: `ruff check app/llm_streaming.py tests/unit/test_llm_streaming.py && ruff format app/llm_streaming.py tests/unit/test_llm_streaming.py`

- [ ] **Step 6: Commit**

```bash
git add app/llm_streaming.py tests/unit/test_llm_streaming.py
git commit -m "phase 5.1: tool-call delta accumulator (app/llm_streaming.py)"
```

---

### Task 2: `Agent.handle_turn()` streams via `LLMClient.stream_chat()`, gains `on_reply_chunk`

**Files:**
- Modify: `app/agent.py` (the `LLMClient` Protocol at line 41-44, and `Agent.handle_turn()`
  at lines 120-170; `SarvamLLMClient` is touched in Task 3, not here)
- Modify: `tests/fixtures/fake_llm.py` (whole file)
- Modify: `tests/integration/test_agent_flow.py` (add two new test functions; five
  existing tests must keep passing unmodified)

**Interfaces:**
- Consumes: `ChatDelta`, `ToolCallDelta`, `ToolCallAccumulator`, `FinishedToolCall` from
  `app.llm_streaming` (Task 1).
- Produces: `LLMClient.stream_chat(messages, tools) -> AsyncIterator[ChatDelta]` — the
  new protocol method every `LLMClient` implementer (Task 3's `SarvamLLMClient`,
  `FakeLLM`) must provide.
- Produces: `Agent.handle_turn(session_id, user_text, *, on_tool_call=None, on_reply_chunk: Callable[[str], Awaitable[None]] | None = None, caller_phone=None) -> str`
  — same return type as before; `on_reply_chunk` is new and optional.

Note: after this task, `SarvamLLMClient` (in the same file) still only has the old
`.chat()` method and does **not** yet implement `stream_chat()` — it's updated in
Task 3. This is fine: nothing in the offline suite constructs
`Agent(SarvamLLMClient(...))` together (that combination only runs live, never
unit-tested), so the offline suite stays green after this task even though the real
app would not run end-to-end until Task 3 lands too.

- [ ] **Step 1: Write the failing tests**

Replace `tests/fixtures/fake_llm.py` entirely:

```python
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
```

In `tests/integration/test_agent_flow.py`, add one new import line after the existing
`from app.agent import FALLBACK_MESSAGE, Agent, LLMResponse, ToolCall` line (that line
itself already has everything this task needs and does not change):

```python
from app.llm_streaming import ChatDelta, ToolCallDelta
```

Then add these two test functions to the end of the file (keep every existing test in
that file untouched):

```python
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

    assert seen == []
    assert reply == "Kal yeh slots free hain."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_agent_flow.py -v`
Expected: all 7 tests FAIL or ERROR — `FakeLLM` no longer has `.chat()`, which
`Agent.handle_turn()` still calls at this point (it hasn't been rewritten yet).

- [ ] **Step 3: Rewrite `Agent.handle_turn()` to consume the stream**

In `app/agent.py`:

Replace the existing `from collections.abc import Callable` import line with:

```python
from collections.abc import AsyncIterator, Awaitable, Callable
```

Add a new import line below it:

```python
from app.llm_streaming import ChatDelta, ToolCallAccumulator
```

Replace the `LLMClient` Protocol (currently):

```python
class LLMClient(Protocol):
    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse: ...
```

with:

```python
class LLMClient(Protocol):
    def stream_chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[ChatDelta]: ...
```

Replace `Agent.handle_turn()`'s body (currently lines 120-170) with:

```python
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
                ToolCall(id=f.id, name=f.name, arguments=f.arguments)
                for f in accumulator.finish()
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
```

Leave `LLMResponse`, `ToolCall`, `SarvamLLMClient` (including its old `.chat()` method)
untouched in this task — `SarvamLLMClient` is rewritten in Task 3.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_agent_flow.py -v`
Expected: 7 passed (5 pre-existing + 2 new)

- [ ] **Step 5: Run the full offline suite to check for collateral breakage**

Run: `pytest -q`
Expected: failures only in `tests/unit/test_sarvam_llm_client.py` (still calling the
now-protocol-mismatched `.chat()` — expected, fixed in Task 3) and
`tests/integration/test_voice_text_equivalence.py` /
`tests/integration/test_turn_metrics.py` (still passing `FakeLLM` the old way — these
should actually still pass since `FakeLLM.responses` accepts plain `LLMResponse`
unchanged; if anything there fails, read the failure before changing Task 2's code —
it means an assumption about this task's backward-compatibility is wrong). Everything
else must pass.

- [ ] **Step 6: Lint and format**

Run: `ruff check app/agent.py tests/fixtures/fake_llm.py tests/integration/test_agent_flow.py && ruff format app/agent.py tests/fixtures/fake_llm.py tests/integration/test_agent_flow.py`

- [ ] **Step 7: Commit**

```bash
git add app/agent.py tests/fixtures/fake_llm.py tests/integration/test_agent_flow.py
git commit -m "phase 5.1: Agent.handle_turn() streams via LLMClient.stream_chat()"
```

---

### Task 3: `SarvamLLMClient.stream_chat()` — real SSE streaming over Sarvam's API

**Files:**
- Modify: `app/agent.py` (`SarvamLLMClient` class — remove `.chat()`/`_parse()`, add
  `.stream_chat()`/`_parse_sse_line()`)
- Modify: `tests/unit/test_sarvam_llm_client.py` (whole file — rewritten against
  `stream_chat()`; the three existing tests there test a method that no longer exists
  after this task)

**Interfaces:**
- Consumes: `ChatDelta`, `ToolCallDelta` from `app.llm_streaming` (Task 1).
- Produces: `SarvamLLMClient.stream_chat(messages, tools) -> AsyncIterator[ChatDelta]`,
  satisfying the `LLMClient` protocol from Task 2.

Sarvam's chat completions API (confirmed from `docs.sarvam.ai`, no live call needed):
`POST https://api.sarvam.ai/v2/chat/completions` with `"stream": true` returns
Server-Sent Events, one `data: {...}` line per `chat.completion.chunk`, terminated by a
`data: [DONE]` line. A chunk may have an empty `choices` array (the
`stream_options.include_usage` trailer) — such chunks carry no delta and must be
skipped, not indexed into.

- [ ] **Step 1: Write the failing tests**

Replace `tests/unit/test_sarvam_llm_client.py` entirely:

```python
import json

import httpx
import pytest
import respx

from app.agent import SarvamLLMClient
from app.llm_streaming import ChatDelta, ToolCallDelta


def _sse(*lines: str) -> str:
    return "".join(f"data: {line}\n\n" for line in lines)


@pytest.mark.asyncio
@respx.mock
async def test_stream_chat_yields_content_deltas():
    body = _sse(
        json.dumps({"choices": [{"delta": {"content": "Namaste"}}]}),
        json.dumps({"choices": [{"delta": {"content": "!"}}]}),
        "[DONE]",
    )
    respx.post("https://api.sarvam.ai/v2/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )
    client = SarvamLLMClient(api_key="fake-key")

    deltas = [
        d
        async for d in client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    ]

    assert deltas == [ChatDelta(content="Namaste"), ChatDelta(content="!")]


@pytest.mark.asyncio
@respx.mock
async def test_stream_chat_parses_fragmented_tool_call_deltas():
    body = _sse(
        json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {"name": "check_slots", "arguments": ""},
                                }
                            ]
                        }
                    }
                ]
            }
        ),
        json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '{"date": "kal"}'}}
                            ]
                        }
                    }
                ]
            }
        ),
        "[DONE]",
    )
    respx.post("https://api.sarvam.ai/v2/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )
    client = SarvamLLMClient(api_key="fake-key")

    deltas = [
        d
        async for d in client.stream_chat(
            messages=[{"role": "user", "content": "kal slot hai?"}], tools=[]
        )
    ]

    assert deltas == [
        ChatDelta(
            tool_call_deltas=[
                ToolCallDelta(index=0, id="call_1", name="check_slots", arguments_fragment="")
            ]
        ),
        ChatDelta(
            tool_call_deltas=[ToolCallDelta(index=0, arguments_fragment='{"date": "kal"}')]
        ),
    ]


@pytest.mark.asyncio
@respx.mock
async def test_stream_chat_skips_done_and_empty_choices_trailer():
    body = _sse(
        json.dumps({"choices": [{"delta": {"content": "ok"}}]}),
        json.dumps({"choices": [], "usage": {"total_tokens": 10}}),
        "[DONE]",
    )
    respx.post("https://api.sarvam.ai/v2/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )
    client = SarvamLLMClient(api_key="fake-key")

    deltas = [
        d
        async for d in client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    ]

    assert deltas == [ChatDelta(content="ok")]


@pytest.mark.asyncio
@respx.mock
async def test_stream_chat_skips_malformed_sse_line_without_raising():
    body = "data: not valid json\n\n" + _sse(
        json.dumps({"choices": [{"delta": {"content": "ok"}}]}), "[DONE]"
    )
    respx.post("https://api.sarvam.ai/v2/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )
    client = SarvamLLMClient(api_key="fake-key")

    deltas = [
        d
        async for d in client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    ]

    assert deltas == [ChatDelta(content="ok")]


@pytest.mark.asyncio
@respx.mock
async def test_stream_chat_sends_stream_true_and_auth_headers():
    route = respx.post("https://api.sarvam.ai/v2/chat/completions").mock(
        return_value=httpx.Response(
            200, text=_sse(json.dumps({"choices": [{"delta": {"content": "ok"}}]}), "[DONE]")
        )
    )
    client = SarvamLLMClient(api_key="fake-key", model="sarvam-105b")

    async for _ in client.stream_chat(
        messages=[{"role": "user", "content": "hi"}], tools=[{"type": "function"}]
    ):
        pass

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer fake-key"
    assert request.headers["api-subscription-key"] == "fake-key"
    body = json.loads(request.content)
    assert body["model"] == "sarvam-105b"
    assert body["tools"] == [{"type": "function"}]
    assert body["stream"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_sarvam_llm_client.py -v`
Expected: FAIL with `AttributeError: 'SarvamLLMClient' object has no attribute 'stream_chat'`

- [ ] **Step 3: Replace `SarvamLLMClient`'s `.chat()`/`_parse()` with `.stream_chat()`**

In `app/agent.py`, add to imports:

```python
from loguru import logger
```

and:

```python
from app.llm_streaming import ChatDelta, ToolCallAccumulator, ToolCallDelta
```

(the `ToolCallAccumulator` import already landed in Task 2; add `ToolCallDelta` to that
same import line.)

In the `SarvamLLMClient` class, delete the existing `chat()` method and `_parse()`
staticmethod, and add in their place:

```python
    async def stream_chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[ChatDelta]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
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
            ) as response:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_sarvam_llm_client.py -v`
Expected: 5 passed

- [ ] **Step 5: Run the full offline suite**

Run: `pytest -q`
Expected: all pass except `tests/integration/test_voice_text_equivalence.py` and
`tests/integration/test_turn_metrics.py` (fixed in Task 4 — they're still exercising
`AgentProcessor`'s old single-`TextFrame`-at-the-end behavior, which hasn't changed
yet in this task).

- [ ] **Step 6: Lint and format**

Run: `ruff check app/agent.py tests/unit/test_sarvam_llm_client.py && ruff format app/agent.py tests/unit/test_sarvam_llm_client.py`

- [ ] **Step 7: Commit**

```bash
git add app/agent.py tests/unit/test_sarvam_llm_client.py
git commit -m "phase 5.1: SarvamLLMClient.stream_chat() (real SSE streaming)"
```

---

### Task 4: `AgentProcessor` pushes a `TextFrame` per chunk, live

**Files:**
- Modify: `app/voice_bot.py` (`AgentProcessor.process_frame`'s `TranscriptionFrame`
  branch — currently lines 165-181)
- Modify: `tests/integration/test_voice_text_equivalence.py` (add two new test
  functions; existing two tests must keep passing unmodified)
- Modify: `tests/integration/test_turn_metrics.py` (add one new test function; existing
  two tests must keep passing unmodified)

**Interfaces:**
- Consumes: `Agent.handle_turn(..., on_reply_chunk=...)` from Task 2.
- Produces: no new public interface — this is the pipeline wiring that makes Task 2's
  streaming actually reach TTS. `AgentProcessor`'s constructor and the frames it emits
  (`LLMFullResponseStartFrame`, `TextFrame`, `LLMFullResponseEndFrame`) are unchanged in
  shape, just timed differently (once per chunk instead of once per full reply).

This task also fixes a correctness gap the spec's pseudocode didn't cover: today,
`Agent.handle_turn()`'s fallback path (hitting `max_tool_rounds`, returning
`FALLBACK_MESSAGE`) never calls `self.llm.stream_chat()` for a final round at all — it
returns directly. That means `on_reply_chunk` is never invoked for that path, so a
naive "only push TextFrames from inside on_reply_chunk" implementation would leave the
caller hearing **nothing** when the agent hits the tool-round ceiling, instead of the
apology message. `AgentProcessor` must push `reply` as a fallback `TextFrame` if no
chunk was ever streamed for that turn.

- [ ] **Step 1: Write the failing tests**

Add these three test functions. First, two in
`tests/integration/test_voice_text_equivalence.py` (add `from app.agent import
FALLBACK_MESSAGE, Agent, LLMResponse, ToolCall` — replacing the existing `from
app.agent import Agent, LLMResponse, ToolCall` import line — and `from app.llm_streaming
import ChatDelta` to that file's imports):

```python
@pytest.mark.asyncio
async def test_voice_frame_pushes_one_text_frame_per_reply_chunk():
    expected_reply = await Agent(
        FakeLLM(
            responses=[[ChatDelta(content="Kal saade paanch "), ChatDelta(content="baje free hai.")]]
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
            TranscriptionFrame(text="kal slot hai?", user_id="caller", timestamp="2026-11-09T10:00:00Z")
        ],
    )

    text_frames = [f for f in down_frames if isinstance(f, TextFrame)]
    assert [f.text for f in text_frames] == ["Kal saade paanch ", "baje free hai."]
    assert "".join(f.text for f in text_frames) == expected_reply


@pytest.mark.asyncio
async def test_fallback_message_is_still_spoken_when_max_tool_rounds_hit():
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
        FakeLLM(responses=[endless_check_slots(str(i)) for i in range(4)]), now=NOW, max_tool_rounds=4
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
```

Then, one in `tests/integration/test_turn_metrics.py` (add `from app.llm_streaming
import ChatDelta` to that file's imports):

```python
@pytest.mark.asyncio
async def test_llm_first_token_marked_only_once_across_multiple_chunks():
    agent = Agent(
        FakeLLM(responses=[[ChatDelta(content="Ek "), ChatDelta(content="pal.")]]), now=NOW
    )
    tracker = TurnTracker()
    call_count = 0
    original_mark = tracker.mark_llm_first_token

    def counting_mark(now: float) -> None:
        nonlocal call_count
        call_count += 1
        original_mark(now)

    tracker.mark_llm_first_token = counting_mark
    processor = AgentProcessor(agent, turn_tracker=tracker)

    await run_test(
        processor,
        frames_to_send=[
            TranscriptionFrame(text="kal slot hai?", user_id="caller", timestamp="2026-11-09T10:00:00Z")
        ],
    )

    assert call_count == 1
    assert tracker.timer.llm_first_token is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_voice_text_equivalence.py tests/integration/test_turn_metrics.py -v`
Expected: the 3 new tests FAIL (old `AgentProcessor` still pushes one `TextFrame` with
the full reply, and never speaks the fallback message); the 4 pre-existing tests in
those two files still PASS unchanged.

- [ ] **Step 3: Rewrite `AgentProcessor.process_frame`'s `TranscriptionFrame` branch**

In `app/voice_bot.py`, replace the `if isinstance(frame, TranscriptionFrame) and
frame.text.strip():` branch (currently lines 165-181) with:

```python
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            if self.turn_tracker is not None:
                self.turn_tracker.mark_stt_final(time.time())

            await self.push_frame(LLMFullResponseStartFrame(), direction)

            first_chunk_seen = False

            async def on_reply_chunk(chunk: str) -> None:
                nonlocal first_chunk_seen
                if self.turn_tracker is not None and not first_chunk_seen:
                    self.turn_tracker.mark_llm_first_token(time.time())
                first_chunk_seen = True
                await self.push_frame(TextFrame(chunk), direction)

            reply = await self.agent.handle_turn(
                self.session_id,
                frame.text,
                on_tool_call=self.on_tool_call,
                on_reply_chunk=on_reply_chunk,
            )

            if not first_chunk_seen and reply:
                # handle_turn() can return a reply (e.g. FALLBACK_MESSAGE, after
                # hitting max_tool_rounds) without ever streaming content through
                # on_reply_chunk - push it now so the caller still hears something.
                if self.turn_tracker is not None:
                    self.turn_tracker.mark_llm_first_token(time.time())
                await self.push_frame(TextFrame(reply), direction)

            if self.on_turn is not None:
                self.on_turn(frame.text, reply)
            await self.push_frame(LLMFullResponseEndFrame(), direction)
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_voice_text_equivalence.py tests/integration/test_turn_metrics.py -v`
Expected: all pass (4 pre-existing + 3 new)

- [ ] **Step 5: Run the full offline suite**

Run: `pytest -q`
Expected: all pass, zero regressions anywhere.

- [ ] **Step 6: Lint and format**

Run: `ruff check app/voice_bot.py tests/integration/test_voice_text_equivalence.py tests/integration/test_turn_metrics.py && ruff format app/voice_bot.py tests/integration/test_voice_text_equivalence.py tests/integration/test_turn_metrics.py`

- [ ] **Step 7: Commit**

```bash
git add app/voice_bot.py tests/integration/test_voice_text_equivalence.py tests/integration/test_turn_metrics.py
git commit -m "phase 5.1: AgentProcessor streams TextFrames per chunk, not per reply"
```

---

### Task 5: Docs + BUILD_PLAN.md

**Files:**
- Modify: `docs/BUILD_PLAN.md` (tick task 5.1, add a close-out note)
- Modify: `docs/architecture.md` (extend the Phase 5 section added for task 5.5)

**Interfaces:** none — documentation only.

- [ ] **Step 1: Run the full offline suite one more time and record the result**

Run: `pytest -q`

Note the pass/fail count and total time for the BUILD_PLAN.md note below.

- [ ] **Step 2: Tick task 5.1 in `docs/BUILD_PLAN.md`**

Change:
```markdown
- [ ] 5.1 Streaming everywhere: switch to the realtime/streaming STT, stream LLM tokens, and start TTS sentence by sentence.
```
to:
```markdown
- [x] 5.1 Streaming everywhere: switch to the realtime/streaming STT, stream LLM tokens, and start TTS sentence by sentence.
```

Immediately below it, add a close-out note (adjust the pass count/time to the Step 1
result):

```markdown
STT was already true-streaming (`SarvamSTTService` is a realtime WebSocket service,
confirmed by reading `pipecat.services.sarvam.stt` — nothing to change there). For LLM
+ TTS: `app/llm_streaming.py` (new) merges Sarvam's fragmented streaming tool-call
deltas; `Agent.handle_turn()` now consumes `LLMClient.stream_chat()` and forwards
content live via a new optional `on_reply_chunk` callback, gated so nothing is spoken
once a tool-call delta has been seen in that round; `AgentProcessor` pushes a
`TextFrame` per chunk instead of one `TextFrame` per full reply.

No custom sentence-splitter was needed: pipecat's `TTSService` already buffers
incoming text and dispatches synthesis per completed sentence
(`TextAggregationMode.SENTENCE`, its existing default) — it just never got a chance to
help before, since all the text used to arrive in one frame at the end. TTS itself
stays on `SarvamHttpTTSService` (not swapped for the WebSocket streaming TTS API) —
deferred to whenever 5.2 (barge-in) is tackled, per the design spec's scoping decision.

Full offline suite: <N> passed in <T>s, zero regressions (every pre-existing test in
`test_agent_flow.py`, `test_sarvam_llm_client.py`, `test_voice_text_equivalence.py` and
`test_turn_metrics.py` still passes unmodified; only new test functions were added).
No live call was needed to implement or verify this — Sarvam's SSE format was taken
from their public docs and mocked with `respx`. A live voice call is the next real
validation, whenever manual Phase 5 testing (the 10-call, 3-person check) happens.

See `docs/superpowers/specs/2026-11-09-voice-streaming-design.md` for the full design
and `docs/superpowers/plans/2026-11-09-voice-streaming.md` for the implementation
breakdown.
```

- [ ] **Step 3: Extend the Phase 5 section of `docs/architecture.md`**

Add this bullet after the existing 5.5 bullet (which ends with "...just guessing."):

```markdown
- **5.1: LLM streaming + sentence-by-sentence TTS, no custom sentence-splitter needed.**
  `app/llm_streaming.py` holds the only genuinely new logic — merging Sarvam's
  fragmented streaming tool-call deltas (id/name once, `arguments` as many small
  string fragments, all keyed by index) into finished tool calls. Everything else
  reuses existing machinery: `Agent.handle_turn()` forwards content deltas live via a
  new `on_reply_chunk` callback (gated off the moment a tool-call delta appears in that
  round, so nothing speculative ever reaches TTS), and pipecat's `TTSService` already
  buffers incoming text into sentences before synthesizing
  (`TextAggregationMode.SENTENCE`, its existing default) — it only needed to actually
  *receive* text incrementally, which it now does.
  - `AgentProcessor` pushes a `TextFrame` per chunk instead of one `TextFrame` per full
    reply, and marks `TurnTracker.llm_first_token` on the first chunk only (same
    overwrite-guard pattern `TTSLatencyMarker` already used for `tts_first_audio`).
  - **Correctness fix, not just a latency change:** `Agent.handle_turn()`'s fallback
    path (hitting `max_tool_rounds`) returns `FALLBACK_MESSAGE` without ever calling
    `on_reply_chunk` — `AgentProcessor` pushes that reply as a `TextFrame` directly if
    no chunk was streamed for the turn, or the caller would hear nothing instead of the
    apology.
  - TTS stays on `SarvamHttpTTSService` (called once per sentence now, via pipecat's
    own aggregation, not once per full reply) rather than switching to Sarvam's
    WebSocket streaming TTS API — that swap is deferred to task 5.2 (barge-in), where
    pipecat's `SarvamTTSService`/`InterruptibleTTSService` is the more natural fit.
```

- [ ] **Step 4: Lint and format the docs touch (no code changed, but confirm the suite is still green)**

Run: `pytest -q`
Expected: same pass count as Step 1 (docs-only change, no code touched).

- [ ] **Step 5: Commit**

```bash
git add docs/BUILD_PLAN.md docs/architecture.md
git commit -m "phase 5.1: streaming LLM tokens + sentence-by-sentence TTS"
```
