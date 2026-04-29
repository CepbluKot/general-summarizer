from __future__ import annotations
import json
import openai
import httpx


class ContextOverflowError(Exception):
    """Raised when LLM returns 400 due to context length exceeded."""


class LLMUnavailableError(Exception):
    """Raised on timeout, connection error, or 502/503."""


_OVERFLOW_KEYWORDS = ("context length", "context_length", "maximum context", "token limit")


class LLMClient:
    def __init__(
        self,
        model: str,
        api_base: str,
        api_key: str,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def call(self, system: str, user: str, output_schema: dict) -> dict:
        try:
            resp = await self._create(system, user)
            raw = resp.choices[0].message.content
            return json.loads(raw)
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

    async def _create(self, system: str, user: str):
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_base,
            http_client=httpx.AsyncClient(verify=False),
            timeout=self.timeout,
        )
        return await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
