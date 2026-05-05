"""Dify Code Node: Format Compress

Формирует System + User Message для LLM Compress ноды.
Промпт фиксированный — пользователь его не задаёт.

Inputs:
  group       (Array[Object]) — группа для сжатия
  output_mode (str)           — "json" | "text"
Outputs:
  system (str) — System Message для LLM Compress
  user   (str) — User Message для LLM Compress
"""
import json

COMPRESS_SYSTEM_JSON = """Compress each item in the provided JSON array to approximately half its size.
Keep the most important information. Preserve the JSON structure of each item.
Return a JSON array with the same number of items.
Output ONLY valid JSON array. No prose, no markdown fences."""

COMPRESS_SYSTEM_TEXT = """Compress each text block to approximately half its size.
Keep the most important information.
Return the same number of blocks separated by \\n\\n---\\n\\n.
Output ONLY the compressed blocks. No prose, no extra formatting."""


def main(group: list, output_mode: str = "json") -> dict:
    if output_mode == "json":
        return {
            "system": COMPRESS_SYSTEM_JSON,
            "user":   json.dumps(group, ensure_ascii=False, indent=2),
        }

    blocks = [item.get("text", "") for item in group]
    return {
        "system": COMPRESS_SYSTEM_TEXT,
        "user":   "\n\n---\n\n".join(blocks),
    }
