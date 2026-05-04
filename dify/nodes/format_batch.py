"""Dify Code Node: Format Batch

Собирает User Message для LLM MAP ноды.

json mode: batch — JSON-строка массива объектов
text mode: batch — строка слов через пробел

Inputs:
  batch         (str) — из parse_input
  output_mode   (str) — "json" | "text"
  output_schema (str) — JSON Schema строкой (только для json mode)
Outputs:
  text (str) — готовый текст для User Message LLM ноды
"""


def main(batch: str, output_mode: str = "json", output_schema: str = "") -> dict:
    parts = []

    if output_mode == "json" and output_schema and output_schema.strip():
        parts.append(
            f"Output JSON Schema:\n{output_schema.strip()}\n\n"
            "Output ONLY valid JSON matching the schema. No prose, no markdown fences."
        )

    parts.append(f"Data:\n{batch}")
    return {"text": "\n\n".join(parts)}
