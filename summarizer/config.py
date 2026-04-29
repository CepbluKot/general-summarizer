from __future__ import annotations
from dataclasses import dataclass


_PROMPT_RESERVE    = 3_000   # токенов на system prompt
_OUTPUT_RESERVE    = 32_768  # токенов на ответ модели


@dataclass
class PipelineConfig:
    input_path: str
    format: str          # "json" | "text"
    schema_hint: str     # "" если text
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
    context_tokens: int = 32000   # ЕДИНСТВЕННЫЙ параметр контекста:
                                   # полный размер окна модели в токенах.
                                   # Бюджеты MAP/REDUCE/output считаются автоматически.
    max_reduce_rounds: int = 20
    max_retries: int = 3           # -1 = бесконечно
    retry_wait_seconds: int = 60
    llm_timeout: int = 10800       # таймаут одного LLM-вызова (сек), default 3 часа
    runs_dir: str | None = "runs"  # папка артефактов; None = не сохранять
    log_file: str | None = None

    # Вычисляемые поля (заполняются в __post_init__, не задаются вручную)
    token_budget: int = 0       # токенов на данные в одном MAP/REDUCE вызове
    max_output_tokens: int = 0  # токенов модели на ответ (передаётся в API)

    def __post_init__(self) -> None:
        # Резервируем на ответ: 16k фиксировано, но не больше 30% контекста
        # (при маленьком контексте 16k может быть много)
        output_reserve = min(_OUTPUT_RESERVE, int(self.context_tokens * 0.30))
        data_budget    = max(1000, self.context_tokens - output_reserve - _PROMPT_RESERVE)
        if self.token_budget == 0:
            self.token_budget = data_budget
        if self.max_output_tokens == 0:
            self.max_output_tokens = output_reserve
