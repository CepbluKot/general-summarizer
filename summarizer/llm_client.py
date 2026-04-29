from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import threading
import time
from pathlib import Path
from typing import Any, ClassVar

import httpx
import instructor
import openai
from instructor.core.exceptions import InstructorRetryException
from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema import validators
from pydantic import RootModel, model_validator

from summarizer.log import get as _log
logger = _log("llm_client")


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
        max_output_tokens: int | None = None,
        audit_dir: "Path | None" = None,
    ) -> None:
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_wait_seconds = retry_wait_seconds
        self.max_output_tokens = max_output_tokens
        self.audit_dir = audit_dir
        self._call_counter = 0
        self._http_client = httpx.AsyncClient(verify=False)

    async def call(self, system: str, user: str, output_schema: dict | None = None) -> dict:
        """Call LLM via Instructor and return a JSON-schema-validated dict.

        Raises:
            ContextOverflowError: Context window exceeded.
            LLMUnavailableError: Timeout, connection error, or 5xx.
        """
        sys_tokens  = len(system) // 3
        user_tokens = len(user) // 3
        n = self._next_call_n()
        logger.debug("LLM call #%04d  system=%d tok  user=%d tok  total=%d tok",
                     n, sys_tokens, user_tokens, sys_tokens + user_tokens)
        self._audit_save(n, "system", system)
        self._audit_save(n, "user",   user)

        attempt = 0
        while True:
            t0 = time.monotonic()
            try:
                result = await self._create(system, user, output_schema)
                elapsed = time.monotonic() - t0
                out_tokens = len(json.dumps(result, ensure_ascii=False)) // 3
                result_str = json.dumps(result, ensure_ascii=False, indent=2)
                self._audit_save(n, "response", result_str)
                logger.debug("LLM #%04d ok  attempt=%d  %.1fs  out=%d tok", n, attempt + 1, elapsed, out_tokens)
                return result
            except openai.BadRequestError as e:
                # 400: context overflow → сигнал для split/compress
                msg = str(e).lower()
                if any(kw in msg for kw in _OVERFLOW_KEYWORDS):
                    logger.warning("LLM #%04d  контекст переполнен (attempt %d)", n, attempt + 1)
                    raise ContextOverflowError(str(e)) from e
                # Другие 400 — не крашимся, логируем и поднимаем как unavailable
                logger.error("LLM #%04d  400 Bad Request (attempt %d): %s", n, attempt + 1, str(e)[:300])
                raise LLMUnavailableError(f"400: {e}") from e

            except openai.RateLimitError as e:
                # 429 Rate Limit — ждём retry_wait_seconds (там указан сброс лимита)
                logger.warning("LLM #%04d  429 Rate Limit (attempt %d) → ждём %ds",
                               n, attempt + 1, self.retry_wait_seconds)
                if self.max_retries != -1 and attempt >= self.max_retries:
                    raise LLMUnavailableError(str(e)) from e
                await asyncio.sleep(self.retry_wait_seconds)
                attempt += 1

            except (openai.APITimeoutError, openai.APIConnectionError) as e:
                # Timeout / connection — ретраим без долгого ожидания
                logger.warning("LLM #%04d  %s (attempt %d) → повтор", n, type(e).__name__, attempt + 1)
                if self.max_retries != -1 and attempt >= self.max_retries:
                    raise LLMUnavailableError(str(e)) from e
                attempt += 1

            except openai.APIStatusError as e:
                if e.status_code in (500, 502, 503, 504):
                    # Серверные ошибки — ждём и ретраим
                    logger.warning("LLM #%04d  HTTP %d (attempt %d) → ждём %ds",
                                   n, e.status_code, attempt + 1, self.retry_wait_seconds)
                    if self.max_retries != -1 and attempt >= self.max_retries:
                        raise LLMUnavailableError(str(e)) from e
                    await asyncio.sleep(self.retry_wait_seconds)
                    attempt += 1
                else:
                    # Другие HTTP ошибки — не крашимся, поднимаем как unavailable
                    logger.error("LLM #%04d  HTTP %d (attempt %d): %s",
                                 n, e.status_code, attempt + 1, str(e)[:200])
                    raise LLMUnavailableError(f"HTTP {e.status_code}: {e}") from e

            except InstructorRetryException as e:
                err_str = str(e)
                if "429" in err_str or "rate limit" in err_str.lower():
                    logger.warning("LLM #%04d  instructor: rate limit exhausted (attempt %d) → ждём %ds",
                                   n, attempt + 1, self.retry_wait_seconds)
                    if self.max_retries != -1 and attempt >= self.max_retries:
                        raise LLMUnavailableError(err_str) from e
                    await asyncio.sleep(self.retry_wait_seconds)
                    attempt += 1
                elif "timeout" in err_str.lower():
                    logger.warning("LLM #%04d  instructor: timeout (attempt %d) → повтор", n, attempt + 1)
                    if self.max_retries != -1 and attempt >= self.max_retries:
                        raise LLMUnavailableError(err_str) from e
                    attempt += 1
                else:
                    logger.error("LLM #%04d  instructor error (attempt %d): %s",
                                 n, attempt + 1, err_str[:300])
                    raise LLMUnavailableError(err_str) from e

    def _next_call_n(self) -> int:
        self._call_counter += 1
        return self._call_counter

    def _audit_save(self, n: int, kind: str, content: str) -> None:
        if self.audit_dir is None:
            return
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        path = self.audit_dir / f"call_{n:04d}_{kind}.txt"
        path.write_text(content, encoding="utf-8")

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

        kwargs: dict = dict(
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
        if self.max_output_tokens:
            kwargs["max_tokens"] = self.max_output_tokens

        response = await client.chat.completions.create(**kwargs)
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
