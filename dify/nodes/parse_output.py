"""Dify Code Node: Parse Output

Парсит ответ LLM в зависимости от output_mode.
В FREE-режиме оборачивает текст в {"text": "..."} чтобы
глобальный Array[Object] работал одинаково в обоих режимах.

Inputs:
  llm_text    (str) — сырой ответ LLM ноды
  output_mode (str) — "json" | "text" (default "json")
Outputs:
  analysis (Object) — распаршенный результат
"""
import json
import re


def main(llm_text: str, output_mode: str = "json") -> dict:
    # убираем <think>...</think> блоки (reasoning models)
    text = re.sub(r"<think>.*?</think>", "", llm_text, flags=re.DOTALL).strip()

    if output_mode == "json":
        return {"analysis": json.loads(text)}
    else:
        return {"analysis": {"text": text}}
