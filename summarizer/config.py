from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class PipelineConfig:
    input_path: str
    format: str                     # "json" | "text"
    schema_hint: str                # "" if text format
    user_prompt: str
    output_schema: dict
    map_prompt_template: str
    reduce_prompt_template: str
    compress_prompt_template: str
    model: str
    api_base: str
    api_key: str
    output_path: str | None
    map_concurrency: int = 5
    context_tokens: int = 32000
    token_budget: int = 0      # 0 = автоматически context_tokens // 2
    max_reduce_rounds: int = 20
    max_retries: int = 3       # -1 = бесконечно
    retry_wait_seconds: int = 60
    llm_timeout: int = 10800  # таймаут одного LLM-вызова в секундах (default 3 часа)
    max_output_tokens: int | None = None  # None = дефолт модели, рекомендуется 8192+
    runs_dir: str | None = "runs"        # папка для артефактов прогона; None = не сохранять
    log_file: str | None = None

    # Автоматические пороги (вычисляются из context_tokens, не задаются руками):
    # pre_compress_threshold = context_tokens * 0.55  — сжать группу до мержа если не влезает
    # compress_trigger       = context_tokens * 0.30  — сжать результат если слишком большой
    # Компрессия всегда целится в 50% от входного размера.

    def __post_init__(self) -> None:
        if self.token_budget == 0:
            if self.max_output_tokens is not None:
                # Знаем размер ответа — точно считаем бюджет:
                # context - output - 3000 (запас на system prompt + schema)
                self.token_budget = max(1000, self.context_tokens - self.max_output_tokens - 3000)
            else:
                # Размер ответа неизвестен — как в оригинале: 55% на данные
                self.token_budget = int(self.context_tokens * 0.55)
