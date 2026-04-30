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
    output_mode: str = "json"  # "json" — JSON schema + валидация; "text" — свободный формат
    map_concurrency: int = 5
    context_tokens: int = 32000   # ЕДИНСТВЕННЫЙ параметр контекста:
                                   # полный размер окна модели в токенах.
                                   # Бюджеты MAP/REDUCE/output считаются автоматически.
    max_reduce_rounds: int = 20
    max_retries: int = 3           # -1 = бесконечно
    retry_wait_seconds: int = 60
    llm_timeout: int = 10800       # таймаут одного LLM-вызова (сек), default 3 часа
    runs_dir: str | None = "runs"    # папка артефактов; None = не сохранять
    resume_run: str | None = None    # имя папки предыдущего запуска для resume
                                     # например: "20260430_100000"
    log_file: str | None = None

    # Вычисляемые поля (заполняются в __post_init__, не задаются вручную)
    token_budget: int = 0       # токенов на данные в одном MAP/REDUCE вызове
    max_output_tokens: int = 0  # токенов модели на ответ (передаётся в API)

    def __post_init__(self) -> None:
        # Если max_output_tokens задан явно — используем его
        # Иначе — авто: 32k или 30% контекста (что меньше)
        if self.max_output_tokens == 0:
            self.max_output_tokens = min(_OUTPUT_RESERVE, int(self.context_tokens * 0.30))
        if self.token_budget == 0:
            self.token_budget = max(1000, self.context_tokens - self.max_output_tokens - _PROMPT_RESERVE)
