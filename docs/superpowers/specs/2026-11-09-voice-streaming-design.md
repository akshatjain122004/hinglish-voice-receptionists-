# Design: streaming LLM tokens + sentence-by-sentence TTS (Phase 5, task 5.1)

## Goal

Phase 4 measured p50/p95 turn latency (`reports/latency_phase4.md`) at ~3.2s / ~9.3s,
far above Phase 5's gate (p50 ≤1.5s, p95 ≤2.5s). The single biggest contributor is
`llm_latency_ms` (p95 5620ms) — the agent currently waits for the LLM's *entire* reply
before anything downstream (TTS) can start. This design streams the LLM's response and
feeds it to TTS incrementally, so the caller starts hearing sentence 1 while sentence 2
is still being generated, instead of waiting for the whole (≤2-sentence) reply.

This is task 5.1 only. It does **not** cover:
- 5.2 (barge-in) — a separate task, though this design's TTS choice (kept as
  `SarvamHttpTTSService`, not swapped for a WebSocket streaming TTS) means 5.2 will
  still need its own work to cancel in-flight/queued TTS.
- 5.4 (filler for slow tools), 5.6 (spoken-number normalisation), 5.7 (prompt
  shortening/caching) — independent tasks, untouched here.
- 5.5 (VAD `stop_secs` tuning) — already shipped separately (see
  `docs/architecture.md`'s Phase 5 section); not touched by this design.
- STT streaming — already true-streaming today (`SarvamSTTService` is a realtime
  WebSocket service, confirmed by reading `pipecat.services.sarvam.stt`); nothing to
  change there.

## Decisions already made (confirmed with the user)

1. **TTS stays on `SarvamHttpTTSService`** (one HTTP call per sentence, not a switch to
   Sarvam's WebSocket streaming TTS API). Lower risk, ships faster; the WebSocket swap
   is deferred to whenever 5.2 (barge-in) is tackled, since pipecat's class for it
   (`SarvamTTSService`, an `InterruptibleTTSService`) is the more natural fit for that
   task anyway.
2. **One streaming code path inside `Agent`**, not two parallel implementations for
   voice vs. text. `Agent.handle_turn()` always consumes a stream internally; the text
   path (`chat_cli.py`, `scripts/run_evals.py`) is unaffected because `handle_turn()`'s
   return value (the full accumulated reply string) doesn't change, and the new
   streaming callback is optional and additive.

## Key implementation finding (changes scope downward)

Pipecat's `TTSService` base class (`pipecat/services/tts_service.py`) already buffers
incoming `TextFrame` text and dispatches synthesis **per completed sentence**
(`TextAggregationMode.SENTENCE`, the default for every `TTSService` including
`SarvamHttpTTSService` — confirmed by reading `_handle_text`/`_text_aggregator.aggregate`).
It already does this correctly *across multiple incoming `TextFrame`s*, mid-stream,
without waiting for `LLMFullResponseEndFrame`.

This means **no custom sentence-splitter is needed in this project's code.** The only
thing missing today is that `AgentProcessor` waits for `Agent.handle_turn()` to return
the *entire* reply before pushing anything — so TTS receives all the text as one
`TextFrame` at once, and its own sentence-boundary buffering never gets a chance to
help. Fixing that is the actual scope of this change: feed TTS incremental text as it
streams from the LLM, and let pipecat's existing TTS aggregation do the rest.

## Components

### `app/llm_streaming.py` (new)

Pure, provider-agnostic, no HTTP/pipecat imports — mirrors `app/metrics.py`'s existing
"no framework imports, trivially unit-testable" pattern.

```python
@dataclass
class ToolCallDelta:
    index: int
    id: str | None = None
    name: str | None = None
    arguments_fragment: str = ""

@dataclass
class ChatDelta:
    content: str | None = None
    tool_call_deltas: list[ToolCallDelta] = field(default_factory=list)

class ToolCallAccumulator:
    """Merges fragmented ToolCallDeltas (OpenAI/Sarvam stream `id`/`name` once,
    `arguments` as many small string fragments, all keyed by `index`) into
    finished `ToolCall`s once the stream ends."""

    def add(self, delta: ToolCallDelta) -> None: ...
    def finish(self) -> list[app.agent.ToolCall]:
        """Concatenates each index's argument fragments and json.loads()s them."""
```

`ToolCallAccumulator.finish()` raising `json.JSONDecodeError` on a malformed/incomplete
argument string is allowed to propagate (same as today: a malformed LLM response is not
a case this project silently papers over elsewhere either).

### `app/agent.py` (modified)

- `LLMClient` Protocol: `chat()` is replaced by
  `stream_chat(messages, tools) -> AsyncIterator[ChatDelta]`.
- `SarvamLLMClient.stream_chat()`: POSTs with `"stream": True` using
  `httpx.AsyncClient.stream(...)`, iterates `response.aiter_lines()`, parses each
  `data: {...}` line as a `chat.completion.chunk` object, skips `data: [DONE]` and any
  chunk with an empty `choices` array (Sarvam's documented `stream_options.include_usage`
  trailer chunk), and yields a `ChatDelta` per chunk. A line that isn't valid
  `data: {json}` is skipped (logged at debug), not fatal — connection-level failures
  (bad status, timeout) still raise, same as today's `chat()`.
- `Agent.handle_turn()` gains one new optional parameter:
  `on_reply_chunk: Callable[[str], Awaitable[None]] | None = None`.

  Per tool round:
  ```python
  accumulator = ToolCallAccumulator()
  content_buffer = ""
  saw_tool_call_delta = False

  async for delta in self.llm.stream_chat(history, tools.TOOL_SCHEMAS):
      if delta.tool_call_deltas:
          saw_tool_call_delta = True
          for tcd in delta.tool_call_deltas:
              accumulator.add(tcd)
      if delta.content:
          content_buffer += delta.content
          if on_reply_chunk is not None and not saw_tool_call_delta:
              await on_reply_chunk(delta.content)

  tool_calls = accumulator.finish()
  if not tool_calls:
      reply = content_buffer
      history.append({"role": "assistant", "content": reply})
      return reply

  # existing tool-dispatch-and-loop logic, unchanged
  ```

  Nothing is spoken speculatively once a tool-call delta has been seen in this round
  (`saw_tool_call_delta` gates `on_reply_chunk`) — this is the safety rule from the
  design discussion: a round that turns out to need a tool call never has partial
  content pushed to TTS first. If `saw_tool_call_delta` flips `True` *after* some
  content was already forwarded (a round that mixes content and tool calls — not
  something OpenAI-compatible APIs do in practice, per Sarvam's own docs implying the
  standard chunk shape, but not a hard guarantee), those already-spoken sentences stand;
  this is a documented, accepted limitation, not something this design engineers around.

  `handle_turn()`'s return value and signature are otherwise unchanged. Callers that
  don't pass `on_reply_chunk` (all of Phase 2/3's text path) see zero behavior change.

### `tests/fixtures/fake_llm.py` (modified)

```python
@dataclass
class FakeLLM:
    responses: list[LLMResponse | list[ChatDelta]]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def stream_chat(self, messages, tools) -> AsyncIterator[ChatDelta]:
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if not self.responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        scripted = self.responses.pop(0)
        for delta in _as_deltas(scripted):  # LLMResponse -> single-chunk deltas; list[ChatDelta] passed through
            yield delta
```

`_as_deltas(LLMResponse)` wraps `content` (if any) into one `ChatDelta(content=...)` and
each `ToolCall` into one `ChatDelta(tool_call_deltas=[ToolCallDelta(index=i, id=tc.id,
name=tc.name, arguments_fragment=json.dumps(tc.arguments))])`. This is why every existing
test (all of which script plain `LLMResponse`s) needs **zero changes** — one scripted
response still yields exactly the frames/behavior it does today. Tests that care about
multi-chunk timing script a `list[ChatDelta]` directly instead.

### `app/voice_bot.py` (modified)

`AgentProcessor.process_frame`'s `TranscriptionFrame` branch changes from "call
`handle_turn()`, then push one `TextFrame` with the full reply" to:

```python
await self.push_frame(LLMFullResponseStartFrame(), direction)

first_chunk_seen = False

async def on_reply_chunk(chunk: str) -> None:
    nonlocal first_chunk_seen
    if self.turn_tracker is not None and not first_chunk_seen:
        self.turn_tracker.mark_llm_first_token(time.time())
        first_chunk_seen = True
    await self.push_frame(TextFrame(chunk), direction)

reply = await self.agent.handle_turn(
    self.session_id, frame.text, on_tool_call=self.on_tool_call, on_reply_chunk=on_reply_chunk
)

await self.push_frame(LLMFullResponseEndFrame(), direction)
```

(`mark_stt_final` and the `on_turn` hook call stay where they are today —
`mark_stt_final` right before `handle_turn()`, `on_turn` after it returns, using the
full `reply` string for `CallLogger`.) The `first_chunk_seen` guard mirrors
`TTSLatencyMarker._marked_this_utterance`'s existing pattern for the same reason:
`TurnTracker.mark_llm_first_token` is a plain setter (overwrites, not idempotent), so
without the guard the tracked value would end up being the *last* chunk's time, not the
first.

## Data flow (voice path)

```
caller stops talking
  -> VAD (0.7s stop_secs, from 5.5) finalizes
  -> SarvamSTTService emits final TranscriptionFrame
  -> AgentProcessor pushes LLMFullResponseStartFrame
  -> Agent.handle_turn() opens Sarvam's SSE stream
       -> each content delta => on_reply_chunk => TextFrame pushed immediately
       -> pipecat's TTSService (existing, unmodified) aggregates text into
          sentences and starts synthesizing sentence 1 as soon as it sees a
          sentence boundary, while sentence 2 is still arriving
  -> stream ends; handle_turn() returns the full reply string
  -> AgentProcessor pushes LLMFullResponseEndFrame
  -> on_turn(user_text, reply) / CallLogger.record_turn (unchanged)
```

Text path (`chat_cli.py`, `scripts/run_evals.py`, `app/evals.py`): calls
`handle_turn()` without `on_reply_chunk`; behavior and return value are byte-for-byte
identical to today.

## Error handling

No new error-handling contract. `stream_chat()`'s connection-level failures
(`httpx.HTTPStatusError`, `httpx.ReadTimeout`, etc.) propagate out of `handle_turn()`
exactly as `chat()`'s `response.raise_for_status()` does today — callers (eval harness,
`chat_cli.py`) already handle that. The only new tolerance is for malformed individual
SSE lines (skip, don't crash the turn over one bad event) — consistent with the
project's existing tolerance for Sarvam's documented network flakiness (Phase 2/3 eval
notes).

## Testing

- `tests/unit/test_llm_streaming.py` (new): `ToolCallAccumulator` merges multi-chunk
  deltas by index, concatenates fragmented `arguments` strings and parses the final
  JSON; a single-chunk tool call still works; a response with zero tool-call deltas
  produces an empty list.
- `tests/unit/test_sarvam_stream_chat.py` (new, `respx`-mocked SSE body — no live call):
  a scripted multi-line SSE response (content-only chunks, a tool-call chunk sequence,
  the `[DONE]` terminator, and Sarvam's documented empty-`choices` usage trailer chunk)
  parses into the expected `ChatDelta` sequence; a malformed line is skipped without
  raising.
- `tests/integration/test_agent_flow.py` (extended): a new case scripts a multi-chunk
  `list[ChatDelta]` final-round response and asserts `on_reply_chunk` fires once per
  chunk, in order, concatenating to the same string `handle_turn()` returns; a new case
  scripts a round with an early content delta followed by a tool-call delta and asserts
  `on_reply_chunk` is never called for that round (the safety gate).
- `tests/integration/test_voice_text_equivalence.py` (extended): a new case with a
  multi-chunk final response asserts multiple `TextFrame`s are pushed, in order, whose
  concatenated text equals the text-path's `handle_turn()` return value. The existing
  single-chunk case is unmodified and still passes (single scripted `LLMResponse` ->
  one chunk -> one `TextFrame`, as today).
- `tests/integration/test_turn_metrics.py` (extended): a new case with 2 content chunks
  asserts `llm_first_token` is set after the first chunk is pushed and is not
  overwritten by the second.
- Full existing offline suite re-run with zero regressions (this is the main regression
  guard, since the FakeLLM auto-wrap is designed specifically so no existing test needs
  to change).
- No live test is required to implement this (SSE format is taken from Sarvam's public
  docs, mocked via `respx`); a live smoke call is left for whenever the user next runs
  live evals/manual voice calls, per CLAUDE.md's "don't run live tests unless asked."

## Open limitation (accepted, not engineered around)

If a provider response ever mixes spoken content with a trailing tool call in the same
round (not standard OpenAI-API behavior, and not something Sarvam's docs suggest
happens), already-forwarded sentences would be followed by a tool-call detour the
caller didn't expect. Flagged here rather than hidden; not defended against, per YAGNI
— there is no evidence this occurs with Sarvam's models.
