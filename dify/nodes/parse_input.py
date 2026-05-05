"""Dify Code Node: Parse Input + Split

Живёт внутри MAP Loop. На каждой итерации читает срез raw_input по offset
и возвращает батч — без материализации всего массива.

json mode:
  - парсит JSON array, берёт срез начиная с offset по token_budget
  - batch — JSON-строка массива объектов текущего батча

text mode:
  - делит по словам, берёт срез начиная с offset по token_budget
  - batch — строка слов батча через пробел

Inputs:
  raw_input    (str)    — исходные данные (глобальная строка)
  offset       (int)    — текущая позиция (loop-переменная)
  input_mode   (str)    — "json" | "text"
  token_budget (str)    — токенов на батч
Outputs:
  batch        (str)    — данные батча для format_batch
  next_offset  (int)    — новый offset для loop-переменной
  has_more     (int)    — 1 если есть ещё данные, 0 если конец
"""
import json


def main(raw_input: str, offset: int, input_mode: str = "json",
         token_budget: str = "6000") -> dict:
    budget = int(token_budget)
    idx    = int(offset)

    if input_mode == "json":
        try:
            rows = json.loads(raw_input.strip())
        except (json.JSONDecodeError, ValueError):
            # fallback: если не валидный JSON — обрабатываем как text
            input_mode = "text"
        else:
            batch  = []
            tokens = 0

            while idx < len(rows):
                row     = rows[idx]
                row_str = json.dumps(row, ensure_ascii=False)
                t       = len(row_str) // 3
                if batch and tokens + t > budget:
                    break
                batch.append(row)
                tokens += t
                idx += 1

            return {
                "batch":       json.dumps(batch, ensure_ascii=False),
                "next_offset": idx,
                "has_more":    1 if idx < len(rows) else 0,
            }

    # text mode
    words  = raw_input.split()
    batch  = []
    tokens = 0

    while idx < len(words):
        word = words[idx]
        t    = len(word) // 3 + 1
        if batch and tokens + t > budget:
            break
        batch.append(word)
        tokens += t
        idx += 1

    return {
        "batch":       " ".join(batch),
        "next_offset": idx,
        "has_more":    1 if idx < len(words) else 0,
    }
