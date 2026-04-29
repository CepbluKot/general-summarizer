from __future__ import annotations

import asyncio
import json
from summarizer.chunker import chunk, estimate_tokens
from summarizer.config import PipelineConfig
from summarizer.llm_client import ContextOverflowError, LLMClient, LLMUnavailableError


class _SafeDict(dict):
    """Passes unknown {keys} through unchanged instead of raising KeyError."""
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _fmt(template: str, **kwargs) -> str:
    return template.format_map(_SafeDict(kwargs))


class Pipeline:
    _MAX_COMPRESS_RETRIES = 5

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

        system = _fmt(
            self.config.map_prompt_template,
            user_prompt=self.config.user_prompt,
            schema_hint=schema_hint_block,
            output_schema=json.dumps(self.config.output_schema, ensure_ascii=False),
            chunk_content="",
        )
        user = "\n".join(rows)

        return await self.llm.call(system, user, self.config.output_schema)

    # ── REDUCE ────────────────────────────────────────────────────────

    async def _run_reduce(self, items: list[dict]) -> dict:
        if len(items) == 1:
            return items[0]

        for _ in range(self.config.max_reduce_rounds):
            if len(items) == 1:
                break
            group_size = self._adaptive_group_size(items)
            next_items: list[dict] = []
            i = 0
            while i < len(items):
                group = items[i:i + group_size]
                i += group_size
                if len(group) == 1:
                    next_items.append(group[0])
                else:
                    merged = await self._merge_group(group)
                    merged = await self._maybe_compress(merged)
                    next_items.append(merged)
            items = next_items

        return items[0]

    def _adaptive_group_size(self, items: list[dict]) -> int:
        sample = items[:min(5, len(items))]
        avg_tokens = sum(
            estimate_tokens(json.dumps(it, ensure_ascii=False)) for it in sample
        ) / len(sample)
        budget = int(self.config.context_tokens * 0.55)
        return max(2, int(budget / max(avg_tokens, 1)))

    async def _merge_group(self, group: list[dict], _depth: int = 0) -> dict:
        """Merge a group of partial results via LLM with full error handling."""
        system = _fmt(
            self.config.reduce_prompt_template,
            user_prompt=self.config.user_prompt,
            output_schema=json.dumps(self.config.output_schema, ensure_ascii=False),
            partial_results="",
        )
        parts = [json.dumps(it, ensure_ascii=False) for it in group]
        user = "\n\n".join(f"### Partial {i+1}\n{p}" for i, p in enumerate(parts))

        try:
            return await self.llm.call(system, user, self.config.output_schema)

        except ContextOverflowError:
            if len(group) > 2 and _depth < 10:
                mid = len(group) // 2
                left = await self._merge_group(group[:mid], _depth + 1)
                right = await self._merge_group(group[mid:], _depth + 1)
                return await self._merge_group([left, right], _depth + 1)
            return await self._compress_and_merge(group)

        except LLMUnavailableError as exc:
            if self._is_server_down(exc):
                await asyncio.sleep(30)
                try:
                    return await self.llm.call(system, user, self.config.output_schema)
                except (LLMUnavailableError, Exception):
                    pass

            current = list(group)
            for attempt in range(self._MAX_COMPRESS_RETRIES):
                current = [await self._compress(it) for it in current]
                parts2 = [json.dumps(it, ensure_ascii=False) for it in current]
                user2 = "\n\n".join(f"### Partial {i+1}\n{p}" for i, p in enumerate(parts2))
                try:
                    return await self.llm.call(system, user2, self.config.output_schema)
                except LLMUnavailableError as retry_exc:
                    if self._is_server_down(retry_exc):
                        await asyncio.sleep(30)
                    if attempt == self._MAX_COMPRESS_RETRIES - 1:
                        return self._programmatic_merge(current)
                except ContextOverflowError:
                    pass
            return self._programmatic_merge(current)

    async def _compress_and_merge(self, group: list[dict]) -> dict:
        """Compress items one by one until merge succeeds."""
        items = list(group)
        system = _fmt(
            self.config.reduce_prompt_template,
            user_prompt=self.config.user_prompt,
            output_schema=json.dumps(self.config.output_schema, ensure_ascii=False),
            partial_results="",
        )
        for i in range(len(items)):
            items[i] = await self._compress(items[i])
            parts = [json.dumps(it, ensure_ascii=False) for it in items]
            user = "\n\n".join(f"### Partial {j+1}\n{p}" for j, p in enumerate(parts))
            try:
                return await self.llm.call(system, user, self.config.output_schema)
            except ContextOverflowError:
                continue
        return self._programmatic_merge(items)

    async def _maybe_compress(self, item: dict) -> dict:
        target_chars = int(self.config.context_tokens * self.config.compression_target_pct / 100) * 3
        if len(json.dumps(item, ensure_ascii=False)) <= target_chars:
            return item
        return await self._compress(item)

    async def _compress(self, item: dict) -> dict:
        user = json.dumps(item, ensure_ascii=False)
        try:
            return await self.llm.call(
                self.config.compress_prompt_template,
                user,
                self.config.output_schema,
            )
        except (ContextOverflowError, LLMUnavailableError):
            return item

    def _programmatic_merge(self, items: list[dict]) -> dict:
        if not items:
            return {}
        result: dict = {}
        for key in items[0]:
            values = [it[key] for it in items if key in it]
            if not values:
                continue
            first = values[0]
            if isinstance(first, list):
                seen: set[str] = set()
                merged_list: list = []
                for v in values:
                    for elem in v:
                        key_str = json.dumps(elem, ensure_ascii=False, sort_keys=True)
                        if key_str not in seen:
                            seen.add(key_str)
                            merged_list.append(elem)
                result[key] = merged_list
            elif isinstance(first, str):
                result[key] = "\n---\n".join(v for v in values if v)
            else:
                result[key] = first
        return result

    @staticmethod
    def _is_server_down(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "502" in msg or "503" in msg or "bad gateway" in msg or "service unavailable" in msg
