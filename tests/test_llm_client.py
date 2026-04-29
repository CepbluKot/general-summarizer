import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from summarizer.llm_client import LLMClient, ContextOverflowError, LLMUnavailableError


@pytest.fixture
def client():
    return LLMClient(model="test", api_base="http://localhost:8000", api_key="sk-test")


def _mock_response(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.mark.asyncio
async def test_call_returns_dict(client):
    payload = {"summary": "all good", "issues": []}
    with patch.object(client, "_create", new=AsyncMock(return_value=payload)):
        result = await client.call("system", "user", {"type": "object"})
    assert result == payload


@pytest.mark.asyncio
async def test_context_overflow_raises(client):
    import openai
    err = openai.BadRequestError(
        message="context length exceeded",
        response=MagicMock(status_code=400),
        body={"error": {"message": "context length exceeded"}},
    )
    with patch.object(client, "_create", new=AsyncMock(side_effect=err)):
        with pytest.raises(ContextOverflowError):
            await client.call("system", "user", {"type": "object"})


@pytest.mark.asyncio
async def test_server_down_raises(client):
    import openai
    err = openai.APIStatusError(
        message="Bad Gateway",
        response=MagicMock(status_code=502),
        body={},
    )
    with patch.object(client, "_create", new=AsyncMock(side_effect=err)):
        with pytest.raises(LLMUnavailableError):
            await client.call("system", "user", {"type": "object"})


@pytest.mark.asyncio
async def test_timeout_raises(client):
    import openai
    err = openai.APITimeoutError(request=MagicMock())
    with patch.object(client, "_create", new=AsyncMock(side_effect=err)):
        with pytest.raises(LLMUnavailableError):
            await client.call("system", "user", {"type": "object"})
