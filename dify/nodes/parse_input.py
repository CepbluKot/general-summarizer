"""Dify Code Node: Parse Input

Нормализует входные данные в Array[Object].

input_mode="json":
  - JSON array of objects  → как есть
  - JSON array of strings  → [{"text": s}, ...]
  - JSON object            → [obj]

input_mode="text":
  - разбивается по строкам → [{"text": line}, ...]
  - пустые строки пропускаются

Inputs:
  raw_input  (str) — данные: JSON или plain text
  input_mode (str) — "json" | "text"
Outputs:
  rows  (Array[Object]) — нормализованный список для split ноды
  count (Number)        — количество строк
"""
import json


def main(raw_input: str, input_mode: str = "json") -> dict:
    text = raw_input.strip()

    if input_mode == "json":
        parsed = json.loads(text)

        if isinstance(parsed, list):
            if not parsed:
                return {"rows": [], "count": 0}
            if isinstance(parsed[0], dict):
                return {"rows": parsed, "count": len(parsed)}
            rows = [{"text": str(item)} for item in parsed]
            return {"rows": rows, "count": len(rows)}

        if isinstance(parsed, dict):
            return {"rows": [parsed], "count": 1}

        return {"rows": [{"text": str(parsed)}], "count": 1}

    # text mode
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows = [{"text": line} for line in lines]
    return {"rows": rows, "count": len(rows)}
