"""Dify Code Node: Format Group

Собирает User Message для LLM REDUCE ноды.

json mode: группа рендерится как JSON-массив + schema инструкция
text mode: группа рендерится как нумерованный список текстовых блоков

Inputs:
  group         (Array[Object]) — из reduce_take_group ноды
  output_mode   (str)           — "json" | "text"
  output_schema (str)           — JSON Schema строкой (только для json mode)
Outputs:
  text (str) — готовый текст для User Message LLM ноды
"""
import json


def main(group: list, output_mode: str = "json", output_schema: str = "") -> dict:
    if output_mode == "json":
        parts = []
        if output_schema and output_schema.strip():
            parts.append(
                f"Output JSON Schema:\n{output_schema.strip()}\n\n"
                "Output ONLY valid JSON matching the schema. No prose, no markdown fences."
            )
        parts.append("Partial analyses to merge:\n" + json.dumps(group, ensure_ascii=False, indent=2))
        return {"text": "\n\n".join(parts)}

    # text mode — склеиваем частичные результаты через разделитель
    blocks = [item.get("text", "") for item in group]
    return {"text": "\n\n---\n\n".join(blocks)}
