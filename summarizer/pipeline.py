from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from summarizer.chunker import chunk, estimate_tokens
from summarizer.config import PipelineConfig
from summarizer.llm_client import ContextOverflowError, LLMClient, LLMUnavailableError
from summarizer.log import get as _log, SEP, SEP2

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

        # Создаём директорию артефактов для этого прогона
        self._run_dir: Path | None = None
        if config.runs_dir:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._run_dir = Path(config.runs_dir) / ts
            self._run_dir.mkdir(parents=True, exist_ok=True)
            (self._run_dir / "map").mkdir(exist_ok=True)
            (self._run_dir / "reduce").mkdir(exist_ok=True)
            (self._run_dir / "llm").mkdir(exist_ok=True)

        self.llm = LLMClient(
            model=config.model,
            api_base=config.api_base,
            api_key=config.api_key,
            timeout=config.llm_timeout,
            max_retries=config.max_retries,
            retry_wait_seconds=config.retry_wait_seconds,
            max_output_tokens=config.max_output_tokens,  # вычислен в PipelineConfig.__post_init__
            audit_dir=self._run_dir / "llm" if self._run_dir else None,
        )

    def _save(self, subdir: str, name: str, data: dict | list) -> Path | None:
        if self._run_dir is None:
            return None
        path = self._run_dir / subdir / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    async def run(self, rows: list[str]) -> dict:
        t0 = time.monotonic()
        cfg = self.config
        logger.info(SEP)
        logger.info("GENERAL SUMMARIZER PIPELINE")
        logger.info("  Модель        : %s", cfg.model)
        logger.info("  API           : %s", cfg.api_base)
        logger.info("  Контекст      : %d токенов  (модель)", cfg.context_tokens)
        logger.info("  Данные/батч   : %d токенов  (%.0f%%)", cfg.token_budget, 100*cfg.token_budget/cfg.context_tokens)
        logger.info("  Ответ модели  : %d токенов  (%.0f%%)", cfg.max_output_tokens, 100*cfg.max_output_tokens/cfg.context_tokens)
        logger.info("  Режим         : %s", cfg.output_mode)
        logger.info("  Параллельность: %d", cfg.map_concurrency)
        logger.info("  Артефакты     : %s", str(self._run_dir) if self._run_dir else "отключено")
        logger.info(SEP)

        if cfg.output_mode == "text":
            partials_text = await self._run_map_text(rows)
            logger.info("")
            result_text = await self._run_reduce_text(partials_text)
            if self._run_dir:
                p = self._run_dir / "result.txt"
                p.write_text(result_text, encoding="utf-8")
                logger.info(SEP)
                logger.info("Готово за %.1fс  →  %s", time.monotonic() - t0, p)
            else:
                logger.info(SEP)
                logger.info("Готово за %.1fс", time.monotonic() - t0)
            logger.info(SEP)
            return result_text  # type: ignore[return-value]

        partials = await self._run_map(rows)

        logger.info("")
        result = await self._run_reduce(partials)

        if self._run_dir:
            p = self._save("", "result.json", result)
            logger.info(SEP)
            logger.info("Готово за %.1fс  →  %s", time.monotonic() - t0, p)
        else:
            logger.info(SEP)
            logger.info("Готово за %.1fс", time.monotonic() - t0)
        logger.info(SEP)
        return result

    # ── MAP ───────────────────────────────────────────────────────────

    def _build_map_system(self) -> str:
        schema_hint = self.config.schema_hint
        schema_hint_block = f"Input data field descriptions:\n{schema_hint}" if schema_hint else ""
        return _fmt(
            self.config.map_prompt_template,
            user_prompt=self.config.user_prompt,
            schema_hint=schema_hint_block,
            output_schema=json.dumps(self.config.output_schema, ensure_ascii=False),
            chunk_content="",
        )

    async def _run_map(self, rows: list[str]) -> list[dict]:
        # Вычитаем реальный размер system prompt из бюджета на данные
        map_system = self._build_map_system()
        prompt_tokens = estimate_tokens(map_system)
        data_budget = max(100, self.config.token_budget - prompt_tokens)
        chunks = chunk(rows, data_budget)
        logger.info("СТАДИЯ 1  ▶  MAP")
        logger.info("  Строк всего   : %d", len(rows))
        logger.info("  Промпт        : ~%d токенов", prompt_tokens)
        logger.info("  Данные/батч   : %d токенов  (%d строк → %d чанков)",
                    data_budget, len(rows), len(chunks))
        t_map = time.monotonic()
        sem = asyncio.Semaphore(self.config.map_concurrency)
        chunk_idx = [0]

        async def process(ch: list[str]) -> dict:
            async with sem:
                idx = chunk_idx[0]
                chunk_idx[0] += 1
                tok = sum(estimate_tokens(r) for r in ch)
                logger.info("  MAP  %d/%d  строк=%d  токенов~%d", idx + 1, len(chunks), len(ch), tok)
                t = time.monotonic()
                result = await self._map_chunk(ch)
                p = self._save("map", f"chunk_{idx:03d}.json", result)
                logger.info("  MAP  %d/%d  ✓  %.1fс%s",
                            idx + 1, len(chunks), time.monotonic() - t,
                            f"  →  {p}" if p else "")
                return result

        results = list(await asyncio.gather(*[process(ch) for ch in chunks]))
        logger.info("СТАДИЯ 1  ✓  MAP завершён за %.1fс  (%d результатов)", time.monotonic() - t_map, len(results))
        return results

    async def _map_chunk(self, rows: list[str], _depth: int = 0) -> dict:
        system = self._build_map_system()
        user = "\n".join(rows)

        try:
            return await self.llm.call(system, user, output_schema=self.config.output_schema)
        except ContextOverflowError:
            if len(rows) <= 1 or _depth >= 8:
                logger.error("MAP chunk too small to split (depth=%d, rows=%d) → empty result", _depth, len(rows))
                return {}
            mid = len(rows) // 2
            logger.warning("MAP context overflow (depth=%d, rows=%d) → splitting in half", _depth, len(rows))
            left  = await self._map_chunk(rows[:mid], _depth + 1)
            right = await self._map_chunk(rows[mid:], _depth + 1)
            return self._programmatic_merge([left, right])

    # ── REDUCE ────────────────────────────────────────────────────────

    async def _run_reduce(self, items: list[dict]) -> dict:
        if len(items) == 1:
            logger.info("СТАДИЯ 2  ▶  REDUCE — один элемент, merge не нужен")
            return items[0]

        logger.info("СТАДИЯ 2  ▶  REDUCE")
        logger.info("  Элементов     : %d", len(items))
        logger.info("  Макс раундов  : %d", self.config.max_reduce_rounds)
        t_reduce = time.monotonic()

        for round_num in range(self.config.max_reduce_rounds):
            if len(items) == 1:
                break
            group_size = self._adaptive_group_size(items)
            n_groups = sum(1 for i in range(0, len(items), group_size) if len(items[i:i+group_size]) > 1)
            logger.info("  %s", SEP2)
            logger.info("  REDUCE раунд %d  |  %d элементов → %d групп по %d",
                        round_num + 1, len(items), n_groups, group_size)
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
                    t_group = time.monotonic()
                    merged = await self._merge_group(group)
                    merged = await self._maybe_compress(merged)
                    p = self._save("reduce", f"round_{round_num+1:02d}_group_{group_num:02d}.json", merged)
                    logger.info("  MERGE  раунд %d  группа %d/%d  ✓  %.1fс%s",
                                round_num + 1, group_num, n_groups, time.monotonic() - t_group,
                                f"  →  {p}" if p else "")
                    next_items.append(merged)
            items = next_items
            logger.info("  REDUCE раунд %d  ✓  %.1fс  →  осталось: %d",
                        round_num + 1, time.monotonic() - t_round, len(items))

        logger.info("СТАДИЯ 2  ✓  REDUCE завершён за %.1fс  →  1 результат", time.monotonic() - t_reduce)
        return items[0]

    def _reduce_budget_tokens(self) -> int:
        """Бюджет токенов на входные саммари в одном REDUCE-вызове."""
        if self.config.max_output_tokens is not None:
            return max(1000, self.config.context_tokens - self.config.max_output_tokens - 3000)
        return int(self.config.context_tokens * 0.55)

    def _adaptive_group_size(self, items: list[dict]) -> int:
        sample = items[:min(5, len(items))]
        avg_tokens = sum(
            estimate_tokens(json.dumps(it, ensure_ascii=False)) for it in sample
        ) / len(sample)
        budget = self._reduce_budget_tokens()
        return max(2, int(budget / max(avg_tokens, 1)))

    async def _merge_group(self, group: list[dict], _depth: int = 0) -> dict:
        """Merge a group of partial results via LLM with full error handling."""
        # Pre-compress: если суммарный payload группы не влезает в REDUCE-бюджет
        pre_compress_threshold = self._reduce_budget_tokens()
        payload_tokens = sum(estimate_tokens(json.dumps(it, ensure_ascii=False)) for it in group)
        if payload_tokens > pre_compress_threshold:
            logger.info("Pre-compressing group (depth=%d): payload=%d tok > threshold=%d tok",
                        _depth, payload_tokens, pre_compress_threshold)
            group = [await self._compress(it) for it in group]

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
            # 1. Сначала пробуем сжать и повторить — часто помогает без сплита
            logger.warning("REDUCE overflow (depth=%d, group=%d) → сжимаем и повторяем", _depth, len(group))
            compressed = [await self._compress(it) for it in group]
            compressed_user = "\n\n".join(
                f"### Partial {i+1}\n{json.dumps(it, ensure_ascii=False)}"
                for i, it in enumerate(compressed)
            )
            try:
                return await self.llm.call(system, compressed_user, output_schema=self.config.output_schema)
            except ContextOverflowError:
                pass  # сжатие не помогло — идём дальше

            # 2. Если группа > 2 — делим пополам (рекурсивно)
            if len(group) > 2 and _depth < 10:
                logger.warning("REDUCE overflow после сжатия (depth=%d, group=%d) → делим пополам", _depth, len(group))
                mid = len(compressed) // 2
                left = await self._merge_group(compressed[:mid], _depth + 1)
                right = await self._merge_group(compressed[mid:], _depth + 1)
                return await self._merge_group([left, right], _depth + 1)

            # 3. Пара — сжимаем по одному
            logger.warning("REDUCE overflow на паре (depth=%d) → compress-and-merge", _depth)
            return await self._compress_and_merge(compressed)

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
        # Сжимаем если результат мержа занимает > 30% контекста
        trigger_tokens = int(self.config.context_tokens * 0.30)
        item_tokens = estimate_tokens(json.dumps(item, ensure_ascii=False))
        if item_tokens <= trigger_tokens:
            return item
        logger.info("Compressing result: %d tok > trigger %d tok (30%% of context)", item_tokens, trigger_tokens)
        return await self._compress(item)

    async def _compress(self, item: dict) -> dict:
        serialized = json.dumps(item, ensure_ascii=False)
        before_tokens = estimate_tokens(serialized)
        target_tokens = max(1, before_tokens // 2)
        system = self.config.compress_prompt_template + (
            f"\n\nTarget size: approximately {target_tokens} tokens (half of current {before_tokens} tokens)."
        )
        try:
            result = await self.llm.call(system, serialized, output_schema=self.config.output_schema)
            after_tokens = estimate_tokens(json.dumps(result, ensure_ascii=False))
            logger.debug("Compress: %d → %d tok (%.0f%%)", before_tokens, after_tokens,
                         100 * after_tokens / before_tokens if before_tokens else 0)
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

    # ── FREE TEXT MODE ────────────────────────────────────────────────

    async def _run_map_text(self, rows: list[str]) -> list[str]:
        map_system = self._build_map_system()
        prompt_tokens = estimate_tokens(map_system)
        data_budget = max(100, self.config.token_budget - prompt_tokens)
        chunks = chunk(rows, data_budget)
        logger.info("СТАДИЯ 1  ▶  MAP (text mode)")
        logger.info("  Строк всего   : %d", len(rows))
        logger.info("  Промпт        : ~%d токенов", prompt_tokens)
        logger.info("  Данные/батч   : %d токенов  (%d строк → %d чанков)",
                    data_budget, len(rows), len(chunks))
        t_map = time.monotonic()
        sem = asyncio.Semaphore(self.config.map_concurrency)
        chunk_idx = [0]

        async def process(ch: list[str]) -> str:
            async with sem:
                idx = chunk_idx[0]
                chunk_idx[0] += 1
                tok = sum(estimate_tokens(r) for r in ch)
                logger.info("  MAP  %d/%d  строк=%d  токенов~%d", idx + 1, len(chunks), len(ch), tok)
                t = time.monotonic()
                text = await self.llm.call_text(map_system, "\n".join(ch))
                p = None
                if self._run_dir:
                    p = self._run_dir / "map" / f"chunk_{idx:03d}.txt"
                    p.write_text(text, encoding="utf-8")
                logger.info("  MAP  %d/%d  ✓  %.1fс%s",
                            idx + 1, len(chunks), time.monotonic() - t,
                            f"  →  {p}" if p else "")
                return text

        results = list(await asyncio.gather(*[process(ch) for ch in chunks]))
        logger.info("СТАДИЯ 1  ✓  MAP завершён за %.1fс  (%d результатов)", time.monotonic() - t_map, len(results))
        return results

    async def _run_reduce_text(self, items: list[str]) -> str:
        if len(items) == 1:
            logger.info("СТАДИЯ 2  ▶  REDUCE (text mode) — один элемент, merge не нужен")
            return items[0]

        logger.info("СТАДИЯ 2  ▶  REDUCE (text mode)")
        logger.info("  Элементов     : %d", len(items))
        t_reduce = time.monotonic()

        system = _fmt(
            self.config.reduce_prompt_template,
            user_prompt=self.config.user_prompt,
            output_schema="",
            partial_results="",
        )
        prompt_tokens = estimate_tokens(system)
        item_budget = max(100, self._reduce_budget_tokens() - prompt_tokens)

        for round_num in range(self.config.max_reduce_rounds):
            if len(items) == 1:
                break
            # группируем по токенному бюджету
            groups: list[list[str]] = []
            current_group: list[str] = []
            current_tokens = 0
            for item in items:
                t = estimate_tokens(item)
                if current_group and current_tokens + t > item_budget:
                    groups.append(current_group)
                    current_group, current_tokens = [], 0
                current_group.append(item)
                current_tokens += t
            if current_group:
                groups.append(current_group)

            logger.info("  REDUCE раунд %d: %d элементов → %d групп",
                        round_num + 1, len(items), len(groups))
            next_items: list[str] = []
            for g_idx, group in enumerate(groups):
                if len(group) == 1:
                    next_items.append(group[0])
                    continue
                user = "\n\n".join(f"### Часть {i+1}\n{p}" for i, p in enumerate(group))
                try:
                    merged = await self.llm.call_text(system, user)
                except (ContextOverflowError, LLMUnavailableError):
                    merged = "\n\n---\n\n".join(group)  # fallback: concat
                if self._run_dir:
                    p = self._run_dir / "reduce" / f"round_{round_num+1:02d}_group_{g_idx+1:02d}.txt"
                    p.write_text(merged, encoding="utf-8")
                next_items.append(merged)
            items = next_items

        logger.info("СТАДИЯ 2  ✓  REDUCE завершён за %.1fс", time.monotonic() - t_reduce)
        return items[0]
