"""Dify Code Node: Reduce — Take Group

Нарезает items на одну группу для мержа по токенному бюджету.

json mode: токены = len(json(item)) // 3
text mode: токены = len(item["text"]) // 3

Inputs:
  items        (Array[Object]) — global
  offset       (Number)        — global
  input_mode   (str)           — "json" | "text"
  token_budget (str)           — токенов на группу
Outputs:
  group      (Array[Object]) — группа для мержа
  new_offset (Number)
  has_more   (Number)        — 1 если после группы ещё есть элементы
"""
import json


def main(items: list, offset: int = 0, input_mode: str = "json",
         token_budget: str = "6000") -> dict:
    budget = int(token_budget)
    idx    = int(offset)

    group  = []
    tokens = 0

    for item in items[idx:]:
        if isinstance(item, str):
            item_str = item
            t = len(item) // 3
            item = {"text": item}
        else:
            item_str = json.dumps(item, ensure_ascii=False)
            t = len(item.get("text", item_str)) // 3 if input_mode == "text" else len(item_str) // 3

        if group and tokens + t > budget:
            break

        group.append(item)
        tokens += t

    new_offset = idx + len(group)
    return {
        "group":      group,
        "new_offset": new_offset,
        "has_more":   1 if new_offset < len(items) else 0,
    }
