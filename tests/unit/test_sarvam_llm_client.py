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
        d async for d in client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[])
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
        ChatDelta(tool_call_deltas=[ToolCallDelta(index=0, arguments_fragment='{"date": "kal"}')]),
    ]


@pytest.mark.asyncio
@respx.mock
async def test_stream_chat_skips_done_but_captures_the_usage_trailer():
    """BUILD_PLAN 5.7a: Sarvam's final chunk carries `usage` (prompt/completion
    token counts) with an empty `choices` array - this is no longer silently
    dropped, it becomes a `ChatDelta(usage=...)` so `Agent.handle_turn()` can
    forward it to a turn's metrics."""
    body = _sse(
        json.dumps({"choices": [{"delta": {"content": "ok"}}]}),
        json.dumps(
            {"choices": [], "usage": {"prompt_tokens": 42, "completion_tokens": 8, "total_tokens": 50}}
        ),
        "[DONE]",
    )
    respx.post("https://api.sarvam.ai/v2/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )
    client = SarvamLLMClient(api_key="fake-key")

    deltas = [
        d async for d in client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    ]

    assert deltas == [
        ChatDelta(content="ok"),
        ChatDelta(usage={"prompt_tokens": 42, "completion_tokens": 8, "total_tokens": 50}),
    ]


@pytest.mark.asyncio
@respx.mock
async def test_stream_chat_skips_an_empty_choices_chunk_with_no_usage():
    body = _sse(
        json.dumps({"choices": [{"delta": {"content": "ok"}}]}),
        json.dumps({"choices": []}),
        "[DONE]",
    )
    respx.post("https://api.sarvam.ai/v2/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )
    client = SarvamLLMClient(api_key="fake-key")

    deltas = [
        d async for d in client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[])
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
        d async for d in client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    ]

    assert deltas == [ChatDelta(content="ok")]


@pytest.mark.asyncio
@respx.mock
async def test_stream_chat_parses_data_line_without_space_after_colon():
    """Finding #2 (final-review): Sarvam's documented prefix is `data: ` (with a
    space), but `_parse_sse_line` must not silently drop the whole stream if the
    real wire format ever omits it - that degrades to total, unexplained silence
    for the caller with no error anywhere."""
    body = (
        "data:"
        + json.dumps({"choices": [{"delta": {"content": "Namaste"}}]})
        + "\n\n"
        + "data:[DONE]\n\n"
    )
    respx.post("https://api.sarvam.ai/v2/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )
    client = SarvamLLMClient(api_key="fake-key")

    deltas = [
        d async for d in client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    ]

    assert deltas == [ChatDelta(content="Namaste")]


@pytest.mark.asyncio
@respx.mock
async def test_stream_chat_yields_nothing_without_raising_when_every_line_is_unparseable():
    """Finding #2 (final-review): a fully-empty/malformed stream must degrade to
    zero deltas, not an exception - the caller (Agent.handle_turn) is expected to
    turn zero deltas into an empty reply, and the warning log (not asserted here,
    just the behavior) is what makes that case visible instead of silent."""
    body = "not even an sse line\n\n: a comment line, not data\n\n"
    respx.post("https://api.sarvam.ai/v2/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )
    client = SarvamLLMClient(api_key="fake-key")

    deltas = [
        d async for d in client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    ]

    assert deltas == []


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
    # BUILD_PLAN 5.7e: sarvam-105b's hybrid thinking mode defaults to "on"
    # (reasoning_effort="low") server-side; explicitly sending `null` (not
    # just omitting the field) is what disables it.
    assert "reasoning_effort" in body
    assert body["reasoning_effort"] is None
