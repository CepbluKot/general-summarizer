import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import ValidationError
from summarizer.llm_client import (
    LLMClient,
    ContextOverflowError,
    LLMUnavailableError,
    _make_json_schema_response_model,
)


@pytest.fixture
def client():
    return LLMClient(model="test", api_base="http://localhost:8000", api_key="sk-test")


class _FakeInstructorCompletions:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.payload, Exception):
            raise self.payload
        return kwargs["response_model"].model_validate(self.payload)


class _FakeInstructorClient:
    def __init__(self, completions: _FakeInstructorCompletions):
        self.chat = MagicMock()
        self.chat.completions = completions


@pytest.mark.asyncio
async def test_call_returns_dict(client):
    payload = {"summary": "all good", "issues": []}
    with patch.object(client, "_create", new=AsyncMock(return_value=payload)):
        result = await client.call("system", "user")
    assert result == payload


@pytest.mark.asyncio
async def test_create_uses_instructor_response_model_and_returns_dict(client):
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}
    completions = _FakeInstructorCompletions({"summary": "ok"})
    fake_instructor_client = _FakeInstructorClient(completions)

    with patch("summarizer.llm_client.openai.AsyncOpenAI", return_value=MagicMock()):
        with patch("summarizer.llm_client.instructor.from_openai", return_value=fake_instructor_client):
            result = await client._create("system", "user", output_schema=schema)

    assert result == {"summary": "ok"}
    assert completions.calls[0]["response_model"].model_json_schema()["properties"] == schema["properties"]
    assert completions.calls[0]["max_retries"] == client.max_retries


def test_dynamic_response_model_validates_json_schema():
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}
    model = _make_json_schema_response_model(schema)

    assert model.model_validate({"summary": "ok"}).root == {"summary": "ok"}
    with pytest.raises(ValidationError, match="Response does not match output JSON Schema"):
        model.model_validate({"summary": 123})


@pytest.mark.asyncio
async def test_create_appends_schema_to_plain_prompt(client):
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}}
    completions = _FakeInstructorCompletions({"summary": "ok"})
    fake_instructor_client = _FakeInstructorClient(completions)

    with patch("summarizer.llm_client.openai.AsyncOpenAI", return_value=MagicMock()):
        with patch("summarizer.llm_client.instructor.from_openai", return_value=fake_instructor_client):
            result = await client._create("plain system", "user", output_schema=schema)

    assert result == {"summary": "ok"}
    assert "Output JSON Schema" in completions.calls[0]["messages"][0]["content"]


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
            await client.call("system", "user")


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
            await client.call("system", "user")


@pytest.mark.asyncio
async def test_timeout_raises(client):
    import openai
    err = openai.APITimeoutError(request=MagicMock())
    with patch.object(client, "_create", new=AsyncMock(side_effect=err)):
        with pytest.raises(LLMUnavailableError):
            await client.call("system", "user")
