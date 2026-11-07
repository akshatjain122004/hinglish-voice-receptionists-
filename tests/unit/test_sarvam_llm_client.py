import json

import httpx
import pytest
import respx

from app.agent import SarvamLLMClient


@pytest.mark.asyncio
@respx.mock
async def test_chat_returns_plain_text_content():
    respx.post("https://api.sarvam.ai/v2/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Namaste! Kaise madad karu?"}}]},
        )
    )
    client = SarvamLLMClient(api_key="fake-key")

    response = await client.chat(messages=[{"role": "user", "content": "hi"}], tools=[])

    assert response.content == "Namaste! Kaise madad karu?"
    assert response.tool_calls == []


@pytest.mark.asyncio
@respx.mock
async def test_chat_parses_tool_calls():
    respx.post("https://api.sarvam.ai/v2/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "check_slots",
                                        "arguments": json.dumps(
                                            {"date": "kal", "service": "cleaning"}
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )
    )
    client = SarvamLLMClient(api_key="fake-key")

    response = await client.chat(messages=[{"role": "user", "content": "kal slot hai?"}], tools=[])

    assert response.content is None
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "check_slots"
    assert response.tool_calls[0].arguments == {"date": "kal", "service": "cleaning"}


@pytest.mark.asyncio
@respx.mock
async def test_chat_sends_auth_headers_and_payload():
    route = respx.post("https://api.sarvam.ai/v2/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    )
    client = SarvamLLMClient(api_key="fake-key", model="sarvam-105b")

    await client.chat(messages=[{"role": "user", "content": "hi"}], tools=[{"type": "function"}])

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer fake-key"
    assert request.headers["api-subscription-key"] == "fake-key"
    body = json.loads(request.content)
    assert body["model"] == "sarvam-105b"
    assert body["tools"] == [{"type": "function"}]
