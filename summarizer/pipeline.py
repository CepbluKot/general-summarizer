from __future__ import annotations

import asyncio
import json
import time
from summarizer.chunker import chunk, estimate_tokens
from summarizer.config import PipelineConfig
from summarizer.llm_client import ContextOverflowError, LLMClient, LLMUnavailableError
from summarizer.log import get as _log

logger = _log("pipeline")


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
        from summarizer.log import setup as _setup
        _setup(config.log_file)
        self.llm = LLMClient(
            model=config.model,
            api_base=config.api_base,
            api_key=config.api_key,
            max_retries=config.max_retries,
            retry_wait_seconds=config.retry_wait_seconds,
            max_output_tokens=config.max_output_tokens,
        )

    async def run(self, rows: list[str]) -> dict:
        t0 = time.monotonic()
        logger.info("Pipeline start: %d rows  token_budget=%d  context_tokens=%d  concurrency=%d",
                    len(rows), self.config.token_budget, self.config.context_tokens, self.config.map_concurrency)
        partials = await self._run_map(rows)
        logger.info("MAP done: %d partials in %.1fs", len(partials), time.monotonic() - t0)
        result = await self._run_reduce(partials)
        logger.info("Pipeline done in %.1fs", time.monotonic() - t0)
        return result

    # ── MAP ───────────────────────────────────────────────────────────

    async def _run_map(self, rows: list[str]) -> list[dict]:
        chunks = chunk(rows, self.config.token_budget)
        logger.info("MAP: %d rows → %d chunks  (token_budget=%d, concurrency=%d)",
                    len(rows), len(chunks), self.config.token_budget, self.config.map_concurrency)
        sem = asyncio.Semaphore(self.config.map_concurrency)
        chunk_idx = [0]

        async def process(ch: list[str]) -> dict:
            async with sem:
                idx = chunk_idx[0]
                chunk_idx[0] += 1
                tok = sum(estimate_tokens(r) for r in ch)
                logger.debug("MAP chunk %d/%d  rows=%d  tokens~%d", idx + 1, len(chunks), len(ch), tok)
                t = time.monotonic()
                result = await self._map_chunk(ch)
                logger.debug("MAP chunk %d/%d done in %.1fs", idx + 1, len(chunks), time.monotonic() - t)
                return result

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

        return await self.llm.call(system, user, output_schema=self.config.output_schema)

    # ── REDUCE ────────────────────────────────────────────────────────

    async def _run_reduce(self, items: list[dict]) -> dict:
        if len(items) == 1:
            logger.info("REDUCE: single item, skipping merge")
            return items[0]

        logger.info("REDUCE start: %d items  max_rounds=%d", len(items), self.config.max_reduce_rounds)
        for round_num in range(self.config.max_reduce_rounds):
            if len(items) == 1:
                break
            group_size = self._adaptive_group_size(items)
            logger.info("REDUCE round %d: %d items → group_size=%d", round_num + 1, len(items), group_size)
            t_round = time.monotonic()
            next_items: list[dict] = []
            i = 0
            group_num = 0
            while i < len(items):
                group = items[i:i + group_size]
                i += group_size
                if len(group) == 1:
                    next_items.append(group[0])
                else:
                    group_num += 1
                    logger.debug("REDUCE round %d group %d: merging %d items", round_num + 1, group_num, len(group))
                    t_group = time.monotonic()
                    merged = await self._merge_group(group)
                    merged = await self._maybe_compress(merged)
                    logger.debug("REDUCE round %d group %d done in %.1fs", round_num + 1, group_num, time.monotonic() - t_group)
                    next_items.append(merged)
            items = next_items
            logger.info("REDUCE round %d done in %.1fs → %d items remaining",
                        round_num + 1, time.monotonic() - t_round, len(items))

        logger.info("REDUCE complete: 1 item")
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
            return await self.llm.call(system, user, output_schema=self.config.output_schema)

        except ContextOverflowError:
            if len(group) > 2 and _depth < 10:
                logger.warning("REDUCE context overflow (depth=%d, group=%d) → splitting in half", _depth, len(group))
                mid = len(group) // 2
                left = await self._merge_group(group[:mid], _depth + 1)
                right = await self._merge_group(group[mid:], _depth + 1)
                return await self._merge_group([left, right], _depth + 1)
            logger.warning("REDUCE context overflow on pair (depth=%d) → compress-and-merge", _depth)
            return await self._compress_and_merge(group)

        except LLMUnavailableError as exc:
            if self._is_server_down(exc):
                logger.warning("REDUCE server down → sleeping 30s and retrying")
                await asyncio.sleep(30)
                try:
                    return await self.llm.call(system, user, output_schema=self.config.output_schema)
                except (LLMUnavailableError, Exception):
                    pass

            current = list(group)
            for attempt in range(self._MAX_COMPRESS_RETRIES):
                logger.warning("REDUCE compress retry %d/%d (LLM unavailable)", attempt + 1, self._MAX_COMPRESS_RETRIES)
                current = [await self._compress(it) for it in current]
                parts2 = [json.dumps(it, ensure_ascii=False) for it in current]
                user2 = "\n\n".join(f"### Partial {i+1}\n{p}" for i, p in enumerate(parts2))
                try:
                    return await self.llm.call(system, user2, output_schema=self.config.output_schema)
                except LLMUnavailableError as retry_exc:
                    if self._is_server_down(retry_exc):
                        await asyncio.sleep(30)
                    if attempt == self._MAX_COMPRESS_RETRIES - 1:
                        logger.error("REDUCE all retries exhausted → programmatic fallback")
                        return self._programmatic_merge(current)
                except ContextOverflowError:
                    pass
            logger.error("REDUCE compress loop ended → programmatic fallback")
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
                return await self.llm.call(system, user, output_schema=self.config.output_schema)
            except ContextOverflowError:
                continue
        return self._programmatic_merge(items)

    async def _maybe_compress(self, item: dict) -> dict:
        target_chars = int(self.config.context_tokens * self.config.compression_target_pct / 100) * 3
        size = len(json.dumps(item, ensure_ascii=False))
        if size <= target_chars:
            return item
        logger.info("Compressing result: %d chars > target %d chars", size, target_chars)
        return await self._compress(item)

    async def _compress(self, item: dict) -> dict:
        user = json.dumps(item, ensure_ascii=False)
        before = len(user)
        try:
            result = await self.llm.call(
                self.config.compress_prompt_template,
                user,
                output_schema=self.config.output_schema,
            )
            after = len(json.dumps(result, ensure_ascii=False))
            logger.debug("Compress: %d → %d chars (%.0f%%)", before, after, 100 * after / before if before else 0)
            return result
        except (ContextOverflowError, LLMUnavailableError):
            logger.warning("Compress failed → returning original")
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
