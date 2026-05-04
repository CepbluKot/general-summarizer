"""Dify Code Node: Split

Нарезает rows на один батч по токенному бюджету.
Порядок строк сохраняется.

json mode: токены = len(json(row)) // 3
text mode: токены = len(row["text"]) // 3

Inputs:
  rows         (Array[Object]) — global
  offset       (Number)        — global (начало = 0)
  input_mode   (str)           — "json" | "text"
  token_budget (str)           — токенов на батч
Outputs:
  batch       (Array[String]) — json-сериализованные строки батча
  next_offset (Number)
  has_more    (Number)        — 1 если есть ещё данные, 0 если конец
"""
import json


def main(rows: list, offset: int = 0, input_mode: str = "json",
         token_budget: str = "6000") -> dict:
    budget = int(token_budget)
    idx    = int(offset)

    batch  = []
    tokens = 0

    while idx < len(rows):
        row     = rows[idx]
        row_str = json.dumps(row, ensure_ascii=False)
        t       = len(row.get("text", row_str)) // 3 if input_mode == "text" else len(row_str) // 3

        if batch and tokens + t > budget:
            break

        batch.append(row_str)
        tokens += t
        idx += 1

    return {
        "batch":       batch,
        "next_offset": idx,
        "has_more":    1 if idx < len(rows) else 0,
    }
