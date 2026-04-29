from __future__ import annotations
import json
import openai
import httpx
import instructor


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
    ) -> None:
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

    async def call(self, system: str, user: str) -> dict:
        """Call LLM via instructor and return parsed JSON dict.

        Uses instructor Mode.JSON with response_model=dict for automatic
        retry on JSON parse failures.

        Raises:
            ContextOverflowError: Context window exceeded.
            LLMUnavailableError: Timeout, connection error, or 5xx.
        """
        try:
            return await self._create(system, user)
        except openai.BadRequestError as e:
            msg = str(e).lower()
            if any(kw in msg for kw in _OVERFLOW_KEYWORDS):
                raise ContextOverflowError(str(e)) from e
            raise
        except (openai.APITimeoutError, openai.APIConnectionError) as e:
            raise LLMUnavailableError(str(e)) from e
        except openai.APIStatusError as e:
            if e.status_code in (502, 503):
                raise LLMUnavailableError(str(e)) from e
            raise
        except Exception as e:
            # instructor wraps retryable errors — re-raise as LLMUnavailableError
            msg = str(e).lower()
            if "retry" in msg or "instructor" in type(e).__name__.lower():
                raise LLMUnavailableError(str(e)) from e
            raise

    async def _create(self, system: str, user: str) -> dict:
        """Make the actual API call via instructor. Separated for easy mocking in tests."""
        openai_client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_base if self.api_base.endswith("/v1") else self.api_base + "/v1",
            http_client=httpx.AsyncClient(verify=False),
            timeout=self.timeout,
            max_retries=0,  # instructor handles retries
        )
        client = instructor.from_openai(openai_client, mode=instructor.Mode.JSON)
        return await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_model=dict,
            temperature=0.2,
            max_retries=self.max_retries,
        )
