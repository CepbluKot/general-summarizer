from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from typing import Any, ClassVar

import httpx
import instructor
import openai
from instructor.core.exceptions import InstructorRetryException
from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema import validators
from pydantic import RootModel, model_validator


class ContextOverflowError(Exception):
    """Raised when LLM returns 400 due to context length exceeded."""


class LLMUnavailableError(Exception):
    """Raised on timeout, connection error, or 502/503."""


_OVERFLOW_KEYWORDS = ("context length", "context_length", "maximum context", "token limit", "prompt is too long", "input is too long")


class LLMClient:
    def __init__(
        self,
        model: str,
        api_base: str,
        api_key: str,
        timeout: float = 120.0,
        max_retries: int = 3,
        retry_wait_seconds: float = 60.0,
    ) -> None:
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries          # -1 = infinite
        self.retry_wait_seconds = retry_wait_seconds
        self._http_client = httpx.AsyncClient(verify=False)

    async def call(self, system: str, user: str, output_schema: dict | None = None) -> dict:
        """Call LLM via Instructor and return a JSON-schema-validated dict.

        Raises:
            ContextOverflowError: Context window exceeded.
            LLMUnavailableError: Timeout, connection error, or 5xx.
        """
        attempt = 0
        while True:
            try:
                return await self._create(system, user, output_schema)
            except openai.BadRequestError as e:
                msg = str(e).lower()
                if any(kw in msg for kw in _OVERFLOW_KEYWORDS):
                    raise ContextOverflowError(str(e)) from e
                raise
            except (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError) as e:
                if self.max_retries != -1 and attempt >= self.max_retries:
                    raise LLMUnavailableError(str(e)) from e
                await asyncio.sleep(self.retry_wait_seconds)
                attempt += 1
            except openai.APIStatusError as e:
                if e.status_code in (502, 503):
                    if self.max_retries != -1 and attempt >= self.max_retries:
                        raise LLMUnavailableError(str(e)) from e
                    await asyncio.sleep(self.retry_wait_seconds)
                    attempt += 1
                else:
                    raise
            except InstructorRetryException as e:
                if "429" in str(e) or "rate limit" in str(e).lower() or "timeout" in str(e).lower():
                    if self.max_retries != -1 and attempt >= self.max_retries:
                        raise LLMUnavailableError(str(e)) from e
                    await asyncio.sleep(self.retry_wait_seconds)
                    attempt += 1
                else:
                    raise LLMUnavailableError(str(e)) from e

    async def _create(self, system: str, user: str, output_schema: dict | None = None) -> dict:
        """Make the actual API call. Separated for easy mocking in tests."""
        openai_client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_base if self.api_base.endswith("/v1") else self.api_base + "/v1",
            http_client=self._http_client,
            timeout=self.timeout,
            max_retries=0,
        )
        client = instructor.from_openai(openai_client, mode=instructor.Mode.JSON)
        response_model = _make_json_schema_response_model(output_schema)

        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": _with_schema_prompt(system, output_schema),
                },
                {"role": "user", "content": user},
            ],
            response_model=response_model,
            temperature=0.2,
            max_retries=self.max_retries,
        )
        return _model_to_dict(response)


def _make_json_schema_response_model(output_schema: dict | None) -> type[RootModel[dict[str, Any]]]:
    schema = _normalize_output_schema(output_schema)
    validator_cls = validators.validator_for(schema)
    validator_cls.check_schema(schema)
    schema_validator = validator_cls(schema)

    class JSONSchemaResponse(RootModel[dict[str, Any]]):
        _output_schema: ClassVar[dict[str, Any]] = schema
        _schema_validator: ClassVar[Any] = schema_validator

        @model_validator(mode="after")
        def validate_against_json_schema(self):
            errors = sorted(self._schema_validator.iter_errors(self.root), key=lambda e: list(e.path))
            if errors:
                raise ValueError(_format_json_schema_errors(errors))
            return self

        @classmethod
        def __get_pydantic_json_schema__(cls, core_schema, handler):
            return cls._output_schema

    return JSONSchemaResponse


def _normalize_output_schema(output_schema: dict | None) -> dict:
    schema = deepcopy(output_schema) if output_schema else {"type": "object"}
    schema.setdefault("title", "SummarizerOutput")
    return schema


def _format_json_schema_errors(errors: list[JSONSchemaValidationError]) -> str:
    details = []
    for error in errors[:10]:
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        details.append(f"{path}: {error.message}")
    if len(errors) > 10:
        details.append(f"... and {len(errors) - 10} more errors")
    return "Response does not match output JSON Schema: " + "; ".join(details)


def _with_schema_prompt(system: str, output_schema: dict | None) -> str:
    if output_schema is None or "JSON Schema" in system:
        return system
    schema_text = json.dumps(output_schema, ensure_ascii=False)
    return f"{system}\n\nOutput JSON Schema:\n{schema_text}\n\nOutput ONLY valid JSON matching the schema."


def _model_to_dict(response: Any) -> dict:
    if isinstance(response, RootModel):
        return response.root
    if hasattr(response, "model_dump"):
        data = response.model_dump()
        if isinstance(data, dict):
            return data
    if isinstance(response, dict):
        return response
    raise TypeError(f"Expected Instructor response to be a dict-compatible model, got {type(response).__name__}")
