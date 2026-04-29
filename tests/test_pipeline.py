import json
import pytest
from unittest.mock import AsyncMock, patch
from summarizer.config import PipelineConfig
from summarizer.pipeline import Pipeline
from pathlib import Path

PROMPTS = Path(__file__).parent.parent / "summarizer" / "prompts"

def make_config(**kwargs):
    defaults = dict(
        input_path="data.json",
        format="json",
        schema_hint="",
        user_prompt="find issues",
        output_schema={"type": "object", "properties": {"issues": {"type": "array", "items": {"type": "string"}}}},
        map_prompt_template=(PROMPTS / "map_default.txt").read_text(),
        reduce_prompt_template=(PROMPTS / "reduce_default.txt").read_text(),
        compress_prompt_template=(PROMPTS / "compress_default.txt").read_text(),
        model="test",
        api_base="http://localhost:8000",
        api_key="sk-test",
        output_path=None,
        map_concurrency=2,
        token_budget=100,
    )
    defaults.update(kwargs)
    return PipelineConfig(**defaults)


@pytest.mark.asyncio
async def test_map_calls_llm_per_chunk():
    rows = ["row1", "row2", "row3"]
    config = make_config(token_budget=10)

    call_count = 0
    async def fake_call(system, user, schema):
        nonlocal call_count
        call_count += 1
        return {"issues": [f"issue from chunk {call_count}"]}

    p = Pipeline(config)
    with patch.object(p.llm, "call", side_effect=fake_call):
        results = await p._run_map(rows)

    assert len(results) >= 1
    assert call_count >= 1
    for r in results:
        assert "issues" in r


@pytest.mark.asyncio
async def test_map_builds_prompt_with_placeholders():
    rows = ["hello world"]
    config = make_config(
        schema_hint="field: description of field",
        user_prompt="summarize this",
    )
    captured = {}
    async def fake_call(system, user, schema):
        captured["system"] = system
        captured["user"] = user
        return {"issues": []}

    p = Pipeline(config)
    with patch.object(p.llm, "call", side_effect=fake_call):
        await p._run_map(rows)

    assert "summarize this" in captured["system"]
    assert "description of field" in captured["system"]
    assert "hello world" in captured["user"]


@pytest.mark.asyncio
async def test_reduce_single_item_returns_as_is():
    config = make_config()
    p = Pipeline(config)
    result = await p._run_reduce([{"issues": ["only one"]}])
    assert result == {"issues": ["only one"]}


@pytest.mark.asyncio
async def test_reduce_merges_multiple():
    config = make_config()
    partials = [{"issues": ["a"]}, {"issues": ["b"]}, {"issues": ["c"]}]

    async def fake_call(system, user, schema):
        return {"issues": ["merged"]}

    p = Pipeline(config)
    with patch.object(p.llm, "call", side_effect=fake_call):
        result = await p._run_reduce(partials)

    assert result == {"issues": ["merged"]}


@pytest.mark.asyncio
async def test_programmatic_merge_combines_arrays():
    config = make_config()
    p = Pipeline(config)
    a = {"issues": ["x", "y"], "count": 2}
    b = {"issues": ["z"], "count": 5}
    merged = p._programmatic_merge([a, b])
    assert set(merged["issues"]) == {"x", "y", "z"}
    assert merged["count"] == 2  # scalar: take first
