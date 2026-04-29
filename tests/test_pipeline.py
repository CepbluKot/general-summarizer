import json
import pytest
from unittest.mock import AsyncMock, patch
from summarizer.config import PipelineConfig
from summarizer.pipeline import Pipeline
from summarizer.llm_client import ContextOverflowError, LLMUnavailableError
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
    async def fake_call(system, user):
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
    async def fake_call(system, user):
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

    async def fake_call(system, user):
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


@pytest.mark.asyncio
async def test_context_overflow_large_group_splits():
    """ContextOverflowError on group > 2 → splits in half and retries."""
    config = make_config()
    p = Pipeline(config)

    call_count = 0
    async def fake_call(system, user):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ContextOverflowError("too long")
        return {"issues": [f"merged-{call_count}"]}

    with patch.object(p.llm, "call", side_effect=fake_call):
        group = [{"issues": [str(i)]} for i in range(4)]
        result = await p._merge_group(group)

    assert "issues" in result
    assert call_count > 1


@pytest.mark.asyncio
async def test_context_overflow_pair_compresses_and_retries():
    """ContextOverflowError on pair → compresses items and retries."""
    config = make_config()
    p = Pipeline(config)

    call_sequence = [
        ContextOverflowError("too long"),
        {"issues": ["compressed-a"]},
        {"issues": ["merged"]},
    ]
    idx = 0
    async def fake_call(system, user):
        nonlocal idx
        result = call_sequence[idx]
        idx += 1
        if isinstance(result, Exception):
            raise result
        return result

    with patch.object(p.llm, "call", side_effect=fake_call):
        group = [{"issues": ["a"]}, {"issues": ["b"]}]
        result = await p._merge_group(group)

    assert result == {"issues": ["merged"]}


@pytest.mark.asyncio
async def test_server_down_waits_and_retries():
    """LLMUnavailableError with 502 → waits and retries."""
    config = make_config()
    p = Pipeline(config)

    call_count = 0
    async def fake_call(system, user):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise LLMUnavailableError("502 Bad Gateway")
        return {"issues": ["ok"]}

    with patch("asyncio.sleep", new=AsyncMock()):
        with patch.object(p.llm, "call", side_effect=fake_call):
            result = await p._merge_group([{"issues": ["a"]}, {"issues": ["b"]}])

    assert result == {"issues": ["ok"]}
    assert call_count == 2


@pytest.mark.asyncio
async def test_programmatic_fallback_after_max_retries():
    """After max compress retries → programmatic merge used."""
    config = make_config()
    p = Pipeline(config)

    async def always_fails(system, user):
        raise LLMUnavailableError("always down")

    with patch("asyncio.sleep", new=AsyncMock()):
        with patch.object(p.llm, "call", side_effect=always_fails):
            group = [{"issues": ["a"]}, {"issues": ["b"]}]
            result = await p._merge_group(group)

    assert "issues" in result
