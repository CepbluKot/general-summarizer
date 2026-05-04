"""Dify Code Node: Format Batch

Собирает User Message для LLM MAP ноды.

json mode: данные рендерятся как JSON-массив объектов + schema инструкция
text mode: данные рендерятся как нумерованный список строк

Inputs:
  batch         (Array[String]) — из split ноды (json-сериализованные строки)
  output_mode   (str)           — "json" | "text"
  output_schema (str)           — JSON Schema строкой (только для json mode)
Outputs:
  text (str) — готовый текст для User Message LLM ноды
"""
import json


def main(batch: list, output_mode: str = "json", output_schema: str = "") -> dict:
    if output_mode == "json":
        parts = []
        if output_schema and output_schema.strip():
            parts.append(
                f"Output JSON Schema:\n{output_schema.strip()}\n\n"
                "Output ONLY valid JSON matching the schema. No prose, no markdown fences."
            )
        rows = [json.loads(s) if isinstance(s, str) else s for s in batch]
        parts.append("Data:\n" + json.dumps(rows, ensure_ascii=False, indent=2))
        return {"text": "\n\n".join(parts)}

    # text mode — извлекаем поле "text" если есть, иначе весь объект строкой
    lines = []
    for i, s in enumerate(batch, 1):
        row = json.loads(s) if isinstance(s, str) else s
        content = row.get("text", json.dumps(row, ensure_ascii=False))
        lines.append(f"{i}. {content}")
    return {"text": "\n".join(lines)}
