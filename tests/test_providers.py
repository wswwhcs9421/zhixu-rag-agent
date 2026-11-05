import asyncio

import httpx
import numpy as np
import pytest

from rag_agent.config import Settings
from rag_agent.providers import DeepSeek, Embeddings, ProviderError


def test_embedding_protocol_orders_and_normalizes_vectors(tmp_path, monkeypatch):
    real_client = httpx.Client
    def handler(request):
        assert request.url.path == "/v1/embeddings"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [0.0, 2.0] + [0.0] * 1022},
            {"index": 0, "embedding": [3.0, 0.0] + [0.0] * 1022},
        ]})
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    settings = Settings(data_dir=tmp_path, bge_mode="api", bge_key="test-key")
    arr = Embeddings(settings).encode(["first", "second"])
    assert arr.shape == (2, 1024)
    assert arr[0, 0] == 1 and arr[1, 1] == 1


@pytest.mark.parametrize("data", [
    [{"index": 0, "embedding": [1.0] * 3}],
    [{"index": 0, "embedding": [0.0] * 1024}],
    [{"index": 1, "embedding": [1.0] * 1024}],
])
def test_invalid_embedding_response_is_rejected(tmp_path, monkeypatch, data):
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": data}))))
    with pytest.raises(ProviderError):
        Embeddings(Settings(data_dir=tmp_path, bge_mode="api")).encode(["text"])


def test_deepseek_protocol_and_reasoning_field(tmp_path, monkeypatch):
    real_client = httpx.AsyncClient
    def handler(request):
        import json
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "provider-specific-v4"
        assert body["tool_choice"] == "required"
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None,
            "reasoning_content": "provider field", "tool_calls": [], "ignored_extra": "ignored"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    settings = Settings(data_dir=tmp_path, deepseek_url="https://example.test/v1", deepseek_key="test-key", deepseek_model="provider-specific-v4")
    result = asyncio.run(DeepSeek(settings).complete([{"role": "user", "content": "question"}], tools=[{"type": "function"}], required=True))
    assert result["reasoning_content"] == "provider field"
    assert "ignored_extra" not in result


def test_deepseek_error_does_not_leak_key_or_upstream_body(tmp_path, monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "secret-key-in-provider-body"}))))
    llm = DeepSeek(Settings(data_dir=tmp_path, deepseek_key="my-private-secret", deepseek_model="configured-model"))
    with pytest.raises(ProviderError, match="HTTP 401") as error:
        asyncio.run(llm.complete([]))
    assert "secret" not in str(error.value)


def test_official_flash_disables_thinking_for_required_tool_loop(tmp_path, monkeypatch):
    real_client = httpx.AsyncClient
    requests = []

    def handler(request):
        import json
        body = json.loads(request.content)
        requests.append(body)
        # Regression for the real API's HTTP 400 when required tool choice is
        # combined with the default thinking mode. Both turns must agree.
        assert body["thinking"] == {"type": "disabled"}
        if len(requests) == 1:
            assert body["tool_choice"] == "required"
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "search_knowledge", "arguments": '{"query":"test"}'}}]}
        else:
            assert "tools" not in body
            message = {"role": "assistant", "content": "Test answer [S1]"}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    llm = DeepSeek(Settings(data_dir=tmp_path, deepseek_key="test-key", deepseek_model="deepseek-flash"))

    async def run():
        messages = [{"role": "user", "content": "question"}]
        message = await llm.complete(messages, tools=[{"type": "function"}], required=True)
        messages.extend([message, {"role": "tool", "tool_call_id": "call-1", "content": "test evidence"}])
        return await llm.complete(messages)

    assert asyncio.run(run())["content"] == "Test answer [S1]"
    assert len(requests) == 2
