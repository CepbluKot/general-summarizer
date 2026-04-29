from __future__ import annotations


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 3)


def chunk(rows: list[str], token_budget: int) -> list[list[str]]:
    if not rows:
        return []

    chunks: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0

    for row in rows:
        t = estimate_tokens(row)
        if current and current_tokens + t > token_budget:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(row)
        current_tokens += t

    if current:
        chunks.append(current)

    return chunks
