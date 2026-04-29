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
    token_budget: int = 0           # 0 = автоматически context_tokens // 2
    compression_target_pct: int = 30
    max_reduce_rounds: int = 20
    max_retries: int = 3            # -1 = бесконечно
    retry_wait_seconds: int = 60
    log_file: str | None = None     # путь к файлу лога, None = только stderr

    def __post_init__(self) -> None:
        if self.token_budget == 0:
            self.token_budget = self.context_tokens // 2
