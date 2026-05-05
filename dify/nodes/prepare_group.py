"""Dify Code Node: Prepare Group

Готовит группу к мержу. Применяет правила:
  1. Если группа > 2 элементов и не влезает в бюджет → берём только 2
  2. Если 2 элемента не влезают → ставим флаг needs_compress
  3. Если влезает → без изменений

Inputs:
  group        (Array[Object]) — из reduce_take_group
  token_budget (str)           — токенов на группу
Outputs:
  group         (Array[Object]) — готовая группа (2 или меньше если урезали)
  needs_compress (Number)       — 1 если нужно сжать перед мержем, 0 если нет
"""
import json


def main(group: list, token_budget: str = "6000") -> dict:
    budget = int(token_budget)

    def tokens(items):
        return sum(len(json.dumps(item, ensure_ascii=False)) // 3 for item in items)

    # влезает как есть
    if tokens(group) <= budget:
        return {"group": group, "needs_compress": 0}

    # не влезает и > 2 → берём только первые 2
    two = group[:2]

    if tokens(two) <= budget:
        return {"group": two, "needs_compress": 0}

    # 2 элемента тоже не влезают → нужно сжатие
    return {"group": two, "needs_compress": 1}
