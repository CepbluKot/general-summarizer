"""Dify Code Node: Append Analysis

Добавляет новый анализ в глобальный аккумулятор.

Inputs:
  analyses     (Array[Object]) — global: накопленные результаты
  new_analysis (Object)        — из parse_output ноды
Outputs:
  analyses (Array[Object]) — обновлённый global
"""


def main(analyses: list, new_analysis: dict) -> dict:
    return {"analyses": analyses + [new_analysis]}
