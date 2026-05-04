"""Dify Code Node: Format Batch for LLM prompt"""
import json

def main(batch: list) -> dict:
    return {"text": json.dumps(batch, ensure_ascii=False, indent=2)}
