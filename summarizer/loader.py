from __future__ import annotations
import json


def load(path: str, format: str) -> list[str]:
    if format == "json":
        return _load_json(path)
    elif format == "text":
        return _load_text(path)
    else:
        raise ValueError(f"Unknown format {format!r}. Supported: json, text")


def _load_json(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"JSON array expected, got {type(data).__name__}")
    return [json.dumps(obj, ensure_ascii=False) for obj in data]


def _load_text(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip()]
