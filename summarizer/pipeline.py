from __future__ import annotations

import asyncio
import json
from summarizer.chunker import chunk, estimate_tokens
from summarizer.config import PipelineConfig
from summarizer.llm_client import ContextOverflowError, LLMClient, LLMUnavailableError


class Pipeline:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.llm = LLMClient(
            model=config.model,
            api_base=config.api_base,
            api_key=config.api_key,
        )

    async def run(self, rows: list[str]) -> dict:
        partials = await self._run_map(rows)
        return await self._run_reduce(partials)

    # ── MAP ───────────────────────────────────────────────────────────

    async def _run_map(self, rows: list[str]) -> list[dict]:
        chunks = chunk(rows, self.config.token_budget)
        sem = asyncio.Semaphore(self.config.map_concurrency)

        async def process(ch: list[str]) -> dict:
            async with sem:
                return await self._map_chunk(ch)

        return list(await asyncio.gather(*[process(ch) for ch in chunks]))

    async def _map_chunk(self, rows: list[str]) -> dict:
        schema_hint = self.config.schema_hint
        schema_hint_block = f"Input data field descriptions:\n{schema_hint}" if schema_hint else ""

        system = self.config.map_prompt_template.format_map({
            "user_prompt": self.config.user_prompt,
            "schema_hint": schema_hint_block,
            "output_schema": json.dumps(self.config.output_schema, ensure_ascii=False),
            "chunk_content": "",
        })
        user = "\n".join(rows)

        return await self.llm.call(system, user, self.config.output_schema)

    # ── REDUCE placeholder (needed so Pipeline can be instantiated) ───

    async def _run_reduce(self, items: list[dict]) -> dict:
        raise NotImplementedError("REDUCE not yet implemented")
