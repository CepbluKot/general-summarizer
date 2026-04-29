# General Summarizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI tool that MAP-REDUCEs any large JSON/text file through an LLM and returns a structured JSON result defined by a user-provided JSON Schema.

**Architecture:** loader reads file → chunker splits by tokens → MAP sends each chunk to LLM in parallel → REDUCE tree-merges partials until 1 result → write JSON output. All prompts user-overridable with defaults. Error handling: context overflow → split/compress; server down → retry/wait; programmatic fallback if all else fails.

**Tech Stack:** Python 3.12, openai (AsyncOpenAI), httpx (SSL disabled), asyncio, pytest, json.

---

## File Map

| File | Responsibility |
|---|---|
| `summarizer/__init__.py` | empty |
| `summarizer/config.py` | `PipelineConfig` dataclass |
| `summarizer/loader.py` | `load(path, format) -> list[str]` |
| `summarizer/chunker.py` | `chunk(rows, budget) -> list[list[str]]` |
| `summarizer/llm_client.py` | `LLMClient` async class + custom exceptions |
| `summarizer/pipeline.py` | `run(rows, config) -> dict` — MAP + REDUCE |
| `summarizer/main.py` | CLI argparse entry point |
| `summarizer/prompts/map_default.txt` | default MAP system prompt |
| `summarizer/prompts/reduce_default.txt` | default REDUCE system prompt |
| `summarizer/prompts/compress_default.txt` | default compress prompt |
| `tests/test_loader.py` | loader unit tests |
| `tests/test_chunker.py` | chunker unit tests |
| `tests/test_llm_client.py` | llm_client tests (mocked) |
| `tests/test_pipeline.py` | pipeline tests (mocked LLM) |
| `README.md` | user guide |
| `CLAUDE.md` | LLM code navigation guide |
| `PROMPT_GUIDE.md` | prompt writing guide |
| `requirements.txt` | dependencies |

---

## Task 1: Project Scaffold

**Files:**
- Create: `summarizer/__init__.py`
- Create: `summarizer/prompts/__init__.py`
- Create: `tests/__init__.py`
- Create: `requirements.txt`

- [ ] **Step 1: Create directory structure**

```bash
cd /home/oleg/Documents/general-summarizer
mkdir -p summarizer/prompts tests
touch summarizer/__init__.py summarizer/prompts/__init__.py tests/__init__.py
```

- [ ] **Step 2: Create requirements.txt**

```
openai>=1.30.0
httpx>=0.27.0
instructor>=1.3.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

File: `requirements.txt`

- [ ] **Step 3: Install dependencies**

```bash
cd /home/oleg/Documents/general-summarizer
pip install -r requirements.txt
```

Expected: all packages install without errors.

- [ ] **Step 4: Commit**

```bash
cd /home/oleg/Documents/general-summarizer
git add .
git commit -m "feat: project scaffold"
```

---

## Task 2: config.py

**Files:**
- Create: `summarizer/config.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_config.py`:

```python
from summarizer.config import PipelineConfig

def test_config_defaults():
    cfg = PipelineConfig(
        input_path="data.json",
        format="json",
        schema_hint="",
        user_prompt="find problems",
        output_schema={"type": "object"},
        map_prompt_template="map {user_prompt}",
        reduce_prompt_template="reduce {user_prompt}",
        compress_prompt_template="compress",
        model="test-model",
        api_base="http://localhost:8000",
        api_key="sk-test",
        output_path=None,
    )
    assert cfg.map_concurrency == 5
    assert cfg.token_budget == 6000
    assert cfg.context_tokens == 32000
    assert cfg.compression_target_pct == 30
    assert cfg.max_reduce_rounds == 20
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/oleg/Documents/general-summarizer
python -m pytest tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement config.py**

```python
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class PipelineConfig:
    input_path: str
    format: str                     # "json" | "text"
    schema_hint: str                # "" if text format
    user_prompt: str
    output_schema: dict
    map_prompt_template: str
    reduce_prompt_template: str
    compress_prompt_template: str
    model: str
    api_base: str
    api_key: str
    output_path: str | None
    map_concurrency: int = 5
    token_budget: int = 6000
    context_tokens: int = 32000
    compression_target_pct: int = 30
    max_reduce_rounds: int = 20
```

File: `summarizer/config.py`

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_config.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add summarizer/config.py tests/test_config.py
git commit -m "feat: add PipelineConfig"
```

---

## Task 3: loader.py

**Files:**
- Create: `summarizer/loader.py`
- Create: `tests/test_loader.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_loader.py`:

```python
import json
import tempfile
import os
from summarizer.loader import load

def _write(content, suffix):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return f.name

def test_load_json_array():
    data = [{"id": 1, "msg": "hello"}, {"id": 2, "msg": "world"}]
    path = _write(json.dumps(data), ".json")
    try:
        rows = load(path, "json")
        assert len(rows) == 2
        assert json.loads(rows[0]) == {"id": 1, "msg": "hello"}
        assert json.loads(rows[1]) == {"id": 2, "msg": "world"}
    finally:
        os.unlink(path)

def test_load_text():
    path = _write("line one\n\nline two\nline three\n", ".txt")
    try:
        rows = load(path, "text")
        assert rows == ["line one", "line two", "line three"]
    finally:
        os.unlink(path)

def test_load_json_raises_on_non_array():
    path = _write('{"key": "value"}', ".json")
    try:
        import pytest
        with pytest.raises(ValueError, match="JSON array"):
            load(path, "json")
    finally:
        os.unlink(path)

def test_load_unknown_format_raises():
    import pytest
    with pytest.raises(ValueError, match="format"):
        load("whatever.csv", "csv")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_loader.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement loader.py**

```python
from __future__ import annotations
import json


def load(path: str, format: str) -> list[str]:
    """Read file and return list of string rows.

    Args:
        path: Path to input file.
        format: "json" (array of objects) or "text" (one row per line).

    Returns:
        list[str] where each element is one unit of data.
    """
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
        raise ValueError(f"JSON file must contain an array at top level, got {type(data).__name__}")
    return [json.dumps(obj, ensure_ascii=False) for obj in data]


def _load_text(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip()]
```

File: `summarizer/loader.py`

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_loader.py -v
```

Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add summarizer/loader.py tests/test_loader.py
git commit -m "feat: add loader (json + text formats)"
```

---

## Task 4: chunker.py

**Files:**
- Create: `summarizer/chunker.py`
- Create: `tests/test_chunker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_chunker.py`:

```python
from summarizer.chunker import chunk, estimate_tokens

def test_estimate_tokens():
    assert estimate_tokens("abc") == 1      # max(1, 3//3)
    assert estimate_tokens("abcdef") == 2   # 6//3
    assert estimate_tokens("") == 1         # min 1

def test_single_chunk_when_fits():
    rows = ["hello", "world", "foo"]
    result = chunk(rows, token_budget=1000)
    assert result == [["hello", "world", "foo"]]

def test_splits_on_budget():
    # Each row ~33 chars = ~11 tokens. budget=20 → 1 row per chunk.
    rows = ["a" * 33, "b" * 33, "c" * 33]
    result = chunk(rows, token_budget=20)
    assert len(result) == 3
    assert result[0] == ["a" * 33]
    assert result[1] == ["b" * 33]
    assert result[2] == ["c" * 33]

def test_empty_rows_returns_empty():
    assert chunk([], token_budget=1000) == []

def test_single_large_row_is_own_chunk():
    # A single row larger than budget still forms a chunk
    big = "x" * 10000
    result = chunk([big], token_budget=10)
    assert result == [[big]]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_chunker.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement chunker.py**

```python
from __future__ import annotations


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 3)


def chunk(rows: list[str], token_budget: int) -> list[list[str]]:
    """Split rows into chunks respecting token_budget per chunk.

    A single row that exceeds the budget forms its own chunk.

    Args:
        rows: List of string rows to chunk.
        token_budget: Max tokens per chunk (estimate: chars // 3).

    Returns:
        List of chunks, each chunk is list[str].
    """
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
```

File: `summarizer/chunker.py`

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_chunker.py -v
```

Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add summarizer/chunker.py tests/test_chunker.py
git commit -m "feat: add chunker with token-based splitting"
```

---

## Task 5: llm_client.py

**Files:**
- Create: `summarizer/llm_client.py`
- Create: `tests/test_llm_client.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_client.py`:

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from summarizer.llm_client import LLMClient, ContextOverflowError, LLMUnavailableError


@pytest.fixture
def client():
    return LLMClient(model="test", api_base="http://localhost:8000", api_key="sk-test")


def _mock_response(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.mark.asyncio
async def test_call_returns_dict(client):
    payload = {"summary": "all good", "issues": []}
    mock_resp = _mock_response(json.dumps(payload))
    with patch.object(client, "_create", new=AsyncMock(return_value=mock_resp)):
        result = await client.call("system", "user", {"type": "object"})
    assert result == payload


@pytest.mark.asyncio
async def test_context_overflow_raises(client):
    import openai
    err = openai.BadRequestError(
        message="context length exceeded",
        response=MagicMock(status_code=400),
        body={"error": {"message": "context length exceeded"}},
    )
    with patch.object(client, "_create", new=AsyncMock(side_effect=err)):
        with pytest.raises(ContextOverflowError):
            await client.call("system", "user", {"type": "object"})


@pytest.mark.asyncio
async def test_server_down_raises(client):
    import openai
    err = openai.APIStatusError(
        message="Bad Gateway",
        response=MagicMock(status_code=502),
        body={},
    )
    with patch.object(client, "_create", new=AsyncMock(side_effect=err)):
        with pytest.raises(LLMUnavailableError):
            await client.call("system", "user", {"type": "object"})


@pytest.mark.asyncio
async def test_timeout_raises(client):
    import openai
    err = openai.APITimeoutError(request=MagicMock())
    with patch.object(client, "_create", new=AsyncMock(side_effect=err)):
        with pytest.raises(LLMUnavailableError):
            await client.call("system", "user", {"type": "object"})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_llm_client.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement llm_client.py**

```python
from __future__ import annotations
import json
import openai
import httpx


class ContextOverflowError(Exception):
    """Raised when LLM returns 400 due to context length exceeded."""


class LLMUnavailableError(Exception):
    """Raised on timeout, connection error, or 502/503."""


_OVERFLOW_KEYWORDS = ("context length", "context_length", "maximum context", "token limit")


class LLMClient:
    def __init__(
        self,
        model: str,
        api_base: str,
        api_key: str,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def call(self, system: str, user: str, output_schema: dict) -> dict:
        """Call LLM and return parsed JSON dict.

        Args:
            system: System prompt text.
            user: User prompt text.
            output_schema: JSON Schema dict — included in system prompt for guidance.

        Raises:
            ContextOverflowError: Context window exceeded.
            LLMUnavailableError: Timeout, connection error, or 5xx.
        """
        try:
            resp = await self._create(system, user)
            raw = resp.choices[0].message.content
            return json.loads(raw)
        except openai.BadRequestError as e:
            msg = str(e).lower()
            if any(kw in msg for kw in _OVERFLOW_KEYWORDS):
                raise ContextOverflowError(str(e)) from e
            raise
        except (openai.APITimeoutError, openai.APIConnectionError) as e:
            raise LLMUnavailableError(str(e)) from e
        except openai.APIStatusError as e:
            if e.status_code in (502, 503):
                raise LLMUnavailableError(str(e)) from e
            raise

    async def _create(self, system: str, user: str):
        """Make the actual API call. Separated for easy mocking in tests."""
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_base,
            http_client=httpx.AsyncClient(verify=False),
            timeout=self.timeout,
        )
        return await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
```

File: `summarizer/llm_client.py`

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_llm_client.py -v
```

Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add summarizer/llm_client.py tests/test_llm_client.py
git commit -m "feat: add LLMClient with error handling"
```

---

## Task 6: Default Prompts

**Files:**
- Create: `summarizer/prompts/map_default.txt`
- Create: `summarizer/prompts/reduce_default.txt`
- Create: `summarizer/prompts/compress_default.txt`

- [ ] **Step 1: Create map_default.txt**

```
You are a data analyst. Your task: {user_prompt}

{schema_hint}

Analyze the provided data fragment and return a PARTIAL result strictly conforming to the JSON Schema below.
This is a partial analysis — data is incomplete. Only capture what is visible in this fragment.

Output JSON Schema:
{output_schema}

Output ONLY valid JSON matching the schema. No prose, no markdown fences.
```

File: `summarizer/prompts/map_default.txt`

- [ ] **Step 2: Create reduce_default.txt**

```
You are a data analyst. User goal: {user_prompt}

Merge the following partial analysis results into one unified final result.
Deduplicate entries, keep the most important information from all inputs.
Strictly conform to the JSON Schema below.

Output JSON Schema:
{output_schema}

Output ONLY valid JSON matching the schema. No prose, no markdown fences.
```

File: `summarizer/prompts/reduce_default.txt`

- [ ] **Step 3: Create compress_default.txt**

```
Compress the following JSON summary to approximately half its current size.
Preserve the most critical information. Keep exactly the same JSON structure and field names.

Output ONLY valid JSON. No prose, no markdown fences.
```

File: `summarizer/prompts/compress_default.txt`

- [ ] **Step 4: Verify prompts are readable**

```bash
python -c "
from pathlib import Path
base = Path('summarizer/prompts')
for f in ['map_default.txt', 'reduce_default.txt', 'compress_default.txt']:
    text = (base / f).read_text()
    assert len(text) > 10, f'{f} is too short'
    print(f'{f}: OK ({len(text)} chars)')
"
```

Expected:
```
map_default.txt: OK (... chars)
reduce_default.txt: OK (... chars)
compress_default.txt: OK (... chars)
```

- [ ] **Step 5: Commit**

```bash
git add summarizer/prompts/
git commit -m "feat: add default MAP/REDUCE/compress prompt templates"
```

---

## Task 7: pipeline.py — MAP phase

**Files:**
- Create: `summarizer/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing tests for MAP**

Create `tests/test_pipeline.py`:

```python
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
    config = make_config(token_budget=10)  # small budget → multiple chunks

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pipeline.py::test_map_calls_llm_per_chunk tests/test_pipeline.py::test_map_builds_prompt_with_placeholders -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement pipeline.py with MAP phase**

```python
from __future__ import annotations

import asyncio
import json
from summarizer.chunker import chunk, estimate_tokens
from summarizer.config import PipelineConfig
from summarizer.llm_client import ContextOverflowError, LLMClient, LLMUnavailableError


class Pipeline:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.llm = LLMClient(
            model=config.model,
            api_base=config.api_base,
            api_key=config.api_key,
        )

    async def run(self, rows: list[str]) -> dict:
        """Full MAP-REDUCE pipeline.

        Args:
            rows: list[str] from loader.

        Returns:
            Final merged dict conforming to output_schema.
        """
        partials = await self._run_map(rows)
        return await self._run_reduce(partials)

    # ── MAP ───────────────────────────────────────────────────────────

    async def _run_map(self, rows: list[str]) -> list[dict]:
        chunks = chunk(rows, self.config.token_budget)
        sem = asyncio.Semaphore(self.config.map_concurrency)

        async def process(ch: list[str]) -> dict:
            async with sem:
                return await self._map_chunk(ch)

        return list(await asyncio.gather(*[process(ch) for ch in chunks]))

    async def _map_chunk(self, rows: list[str]) -> dict:
        schema_hint = self.config.schema_hint
        schema_hint_block = f"Input data field descriptions:\n{schema_hint}" if schema_hint else ""

        system = self.config.map_prompt_template.format_map({
            "user_prompt": self.config.user_prompt,
            "schema_hint": schema_hint_block,
            "output_schema": json.dumps(self.config.output_schema, ensure_ascii=False),
            "chunk_content": "",   # not used in system
        })
        user = "\n".join(rows)

        return await self.llm.call(system, user, self.config.output_schema)
```

File: `summarizer/pipeline.py`

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_pipeline.py::test_map_calls_llm_per_chunk tests/test_pipeline.py::test_map_builds_prompt_with_placeholders -v
```

Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add summarizer/pipeline.py tests/test_pipeline.py
git commit -m "feat: add Pipeline with MAP phase"
```

---

## Task 8: pipeline.py — REDUCE phase

**Files:**
- Modify: `summarizer/pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing REDUCE tests**

Append to `tests/test_pipeline.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pipeline.py::test_reduce_single_item_returns_as_is tests/test_pipeline.py::test_reduce_merges_multiple tests/test_pipeline.py::test_programmatic_merge_combines_arrays -v
```

Expected: FAIL (AttributeError — methods don't exist yet)

- [ ] **Step 3: Add REDUCE methods to pipeline.py**

Append to the `Pipeline` class in `summarizer/pipeline.py`:

```python
    # ── REDUCE ────────────────────────────────────────────────────────

    async def _run_reduce(self, items: list[dict]) -> dict:
        if len(items) == 1:
            return items[0]

        for _ in range(self.config.max_reduce_rounds):
            if len(items) == 1:
                break
            group_size = self._adaptive_group_size(items)
            next_items: list[dict] = []
            i = 0
            while i < len(items):
                group = items[i:i + group_size]
                i += group_size
                if len(group) == 1:
                    next_items.append(group[0])
                else:
                    merged = await self._merge_group(group)
                    merged = await self._maybe_compress(merged)
                    next_items.append(merged)
            items = next_items

        return items[0]

    def _adaptive_group_size(self, items: list[dict]) -> int:
        sample = items[:min(5, len(items))]
        avg_tokens = sum(
            estimate_tokens(json.dumps(it, ensure_ascii=False)) for it in sample
        ) / len(sample)
        budget = int(self.config.context_tokens * 0.55)
        return max(2, int(budget / max(avg_tokens, 1)))

    async def _merge_group(self, group: list[dict]) -> dict:
        system = self.config.reduce_prompt_template.format_map({
            "user_prompt": self.config.user_prompt,
            "output_schema": json.dumps(self.config.output_schema, ensure_ascii=False),
            "partial_results": "",
        })
        parts = [json.dumps(it, ensure_ascii=False) for it in group]
        user = "\n\n".join(f"### Partial {i+1}\n{p}" for i, p in enumerate(parts))
        return await self.llm.call(system, user, self.config.output_schema)

    async def _maybe_compress(self, item: dict) -> dict:
        target_chars = int(self.config.context_tokens * self.config.compression_target_pct / 100) * 3
        if len(json.dumps(item, ensure_ascii=False)) <= target_chars:
            return item
        return await self._compress(item)

    async def _compress(self, item: dict) -> dict:
        user = json.dumps(item, ensure_ascii=False)
        try:
            return await self.llm.call(
                self.config.compress_prompt_template,
                user,
                self.config.output_schema,
            )
        except ContextOverflowError:
            return item

    def _programmatic_merge(self, items: list[dict]) -> dict:
        """Schema-agnostic merge: arrays concatenated, scalars from first item."""
        if not items:
            return {}
        result: dict = {}
        for key in items[0]:
            values = [it[key] for it in items if key in it]
            if not values:
                continue
            first = values[0]
            if isinstance(first, list):
                seen: set[str] = set()
                merged_list: list = []
                for v in values:
                    for elem in v:
                        key_str = json.dumps(elem, ensure_ascii=False, sort_keys=True)
                        if key_str not in seen:
                            seen.add(key_str)
                            merged_list.append(elem)
                result[key] = merged_list
            elif isinstance(first, str):
                result[key] = "\n---\n".join(v for v in values if v)
            else:
                result[key] = first  # numbers, bools: take first
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_pipeline.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add summarizer/pipeline.py tests/test_pipeline.py
git commit -m "feat: add REDUCE phase with adaptive grouping and compression"
```

---

## Task 9: pipeline.py — Error Handling

**Files:**
- Modify: `summarizer/pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing error-handling tests**

Append to `tests/test_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_context_overflow_large_group_splits():
    """ContextOverflowError on group > 2 → splits in half and retries."""
    config = make_config()
    p = Pipeline(config)

    call_count = 0
    async def fake_call(system, user, schema):
        nonlocal call_count
        call_count += 1
        # First call (group of 4) → overflow; subsequent calls succeed
        if call_count == 1:
            raise ContextOverflowError("too long")
        return {"issues": [f"merged-{call_count}"]}

    with patch.object(p.llm, "call", side_effect=fake_call):
        group = [{"issues": [str(i)]} for i in range(4)]
        result = await p._merge_group(group)

    assert "issues" in result
    assert call_count > 1  # split and retried


@pytest.mark.asyncio
async def test_context_overflow_pair_compresses_and_retries():
    """ContextOverflowError on pair → compresses items and retries."""
    config = make_config()
    p = Pipeline(config)

    call_sequence = [
        ContextOverflowError("too long"),   # first merge attempt fails
        {"issues": ["compressed-a"]},       # compress item 0
        {"issues": ["merged"]},             # merge after compression succeeds
    ]
    idx = 0
    async def fake_call(system, user, schema):
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
    async def fake_call(system, user, schema):
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

    async def always_fails(system, user, schema):
        raise LLMUnavailableError("always down")

    with patch("asyncio.sleep", new=AsyncMock()):
        with patch.object(p.llm, "call", side_effect=always_fails):
            group = [{"issues": ["a"]}, {"issues": ["b"]}]
            result = await p._merge_group(group)

    assert "issues" in result  # programmatic merge returned something
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pipeline.py::test_context_overflow_large_group_splits tests/test_pipeline.py::test_context_overflow_pair_compresses_and_retries tests/test_pipeline.py::test_server_down_waits_and_retries tests/test_pipeline.py::test_programmatic_fallback_after_max_retries -v
```

Expected: FAIL (logic not implemented yet)

- [ ] **Step 3: Replace _merge_group with full error handling**

Replace the `_merge_group` method in `summarizer/pipeline.py`:

```python
    _MAX_COMPRESS_RETRIES = 5

    async def _merge_group(self, group: list[dict], _depth: int = 0) -> dict:
        """Merge a group of partial results via LLM with full error handling."""
        system = self.config.reduce_prompt_template.format_map({
            "user_prompt": self.config.user_prompt,
            "output_schema": json.dumps(self.config.output_schema, ensure_ascii=False),
            "partial_results": "",
        })
        parts = [json.dumps(it, ensure_ascii=False) for it in group]
        user = "\n\n".join(f"### Partial {i+1}\n{p}" for i, p in enumerate(parts))

        try:
            return await self.llm.call(system, user, self.config.output_schema)

        except ContextOverflowError:
            if len(group) > 2 and _depth < 10:
                mid = len(group) // 2
                left = await self._merge_group(group[:mid], _depth + 1)
                right = await self._merge_group(group[mid:], _depth + 1)
                return await self._merge_group([left, right], _depth + 1)
            # pair or deep recursion → compress-and-retry
            return await self._compress_and_merge(group)

        except LLMUnavailableError as exc:
            if self._is_server_down(exc):
                await asyncio.sleep(30)
                try:
                    return await self.llm.call(system, user, self.config.output_schema)
                except (LLMUnavailableError, Exception):
                    pass

            # timeout or persistent failure → compress loop
            current = list(group)
            for attempt in range(self._MAX_COMPRESS_RETRIES):
                current = [await self._compress(it) for it in current]
                try:
                    parts2 = [json.dumps(it, ensure_ascii=False) for it in current]
                    user2 = "\n\n".join(f"### Partial {i+1}\n{p}" for i, p in enumerate(parts2))
                    return await self.llm.call(system, user2, self.config.output_schema)
                except LLMUnavailableError:
                    if self._is_server_down(exc):
                        await asyncio.sleep(30)
                    if attempt == self._MAX_COMPRESS_RETRIES - 1:
                        return self._programmatic_merge(current)
                except ContextOverflowError:
                    pass  # keep compressing
            return self._programmatic_merge(current)

    async def _compress_and_merge(self, group: list[dict]) -> dict:
        """Compress items one by one until merge succeeds."""
        items = list(group)
        system = self.config.reduce_prompt_template.format_map({
            "user_prompt": self.config.user_prompt,
            "output_schema": json.dumps(self.config.output_schema, ensure_ascii=False),
            "partial_results": "",
        })
        for i in range(len(items)):
            items[i] = await self._compress(items[i])
            try:
                parts = [json.dumps(it, ensure_ascii=False) for it in items]
                user = "\n\n".join(f"### Partial {j+1}\n{p}" for j, p in enumerate(parts))
                return await self.llm.call(system, user, self.config.output_schema)
            except ContextOverflowError:
                continue
        return self._programmatic_merge(items)

    @staticmethod
    def _is_server_down(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "502" in msg or "503" in msg or "bad gateway" in msg or "service unavailable" in msg
```

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/test_pipeline.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add summarizer/pipeline.py tests/test_pipeline.py
git commit -m "feat: add full error handling to REDUCE (overflow, retry, fallback)"
```

---

## Task 10: main.py

**Files:**
- Create: `summarizer/main.py`

- [ ] **Step 1: Implement main.py**

```python
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _load_prompt(path: str | None, default_name: str) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return (Path(__file__).parent / "prompts" / default_name).read_text(encoding="utf-8")


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="summarizer",
        description="MAP-REDUCE summarizer for JSON/text files",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    inp = p.add_argument_group("Input")
    inp.add_argument("--input", required=True, help="Path to input file")
    inp.add_argument("--format", choices=["json", "text"], default="json")
    inp.add_argument("--schema-hint", default="", help="Field descriptions (json format only)")

    task = p.add_argument_group("Task")
    task.add_argument("--prompt", required=True, help="Summarization goal/instructions")
    task.add_argument("--output-schema", required=True, help="Path to JSON Schema file for output")

    prompts = p.add_argument_group("Prompts (optional overrides)")
    prompts.add_argument("--map-prompt", default=None)
    prompts.add_argument("--reduce-prompt", default=None)
    prompts.add_argument("--compress-prompt", default=None)

    llm = p.add_argument_group("LLM")
    llm.add_argument("--model", default=os.getenv("LLM_MODEL", "default"))
    llm.add_argument("--api-base", default=os.getenv("LLM_API_BASE", "http://localhost:8000"))
    llm.add_argument("--api-key", default=os.getenv("LLM_API_KEY", "sk-placeholder"))

    out = p.add_argument_group("Output")
    out.add_argument("--output", "-o", default=None, help="Output file (default: stdout)")

    pipe = p.add_argument_group("Pipeline")
    pipe.add_argument("--map-concurrency", type=int, default=5)
    pipe.add_argument("--token-budget", type=int, default=6000)
    pipe.add_argument("--context-tokens", type=int, default=32000)
    pipe.add_argument("--max-reduce-rounds", type=int, default=20)

    return p.parse_args(argv)


async def _main(argv=None) -> int:
    args = _parse_args(argv)

    from summarizer.config import PipelineConfig
    from summarizer.loader import load
    from summarizer.pipeline import Pipeline

    output_schema = json.loads(Path(args.output_schema).read_text(encoding="utf-8"))

    config = PipelineConfig(
        input_path=args.input,
        format=args.format,
        schema_hint=args.schema_hint,
        user_prompt=args.prompt,
        output_schema=output_schema,
        map_prompt_template=_load_prompt(args.map_prompt, "map_default.txt"),
        reduce_prompt_template=_load_prompt(args.reduce_prompt, "reduce_default.txt"),
        compress_prompt_template=_load_prompt(args.compress_prompt, "compress_default.txt"),
        model=args.model,
        api_base=args.api_base,
        api_key=args.api_key,
        output_path=args.output,
        map_concurrency=args.map_concurrency,
        token_budget=args.token_budget,
        context_tokens=args.context_tokens,
        max_reduce_rounds=args.max_reduce_rounds,
    )

    rows = load(args.input, args.format)
    if not rows:
        print("ERROR: input file is empty", file=sys.stderr)
        return 1

    pipeline = Pipeline(config)
    result = await pipeline.run(rows)

    output = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Result written to: {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


def main() -> None:
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
```

File: `summarizer/main.py`

- [ ] **Step 2: Verify CLI help works**

```bash
cd /home/oleg/Documents/general-summarizer
python -m summarizer.main --help
```

Expected: prints help without errors.

- [ ] **Step 3: Commit**

```bash
git add summarizer/main.py
git commit -m "feat: add CLI entry point"
```

---

## Task 11: Documentation

**Files:**
- Create: `README.md`
- Create: `CLAUDE.md`
- Create: `PROMPT_GUIDE.md`

- [ ] **Step 1: Create README.md**

```markdown
# General Summarizer

CLI tool that MAP-REDUCEs any large JSON or text file through an LLM and returns a structured JSON result.

## Install

```bash
pip install -r requirements.txt
```

## Quick Start

```bash
python -m summarizer.main \
  --input data.json \
  --format json \
  --schema-hint "id: record id, message: event text, level: severity" \
  --prompt "Find the top 5 issues and group them by severity" \
  --output-schema schema.json \
  --model qwen2.5-72b \
  --api-base http://localhost:8000 \
  --api-key sk-your-key \
  --output result.json
```

## Output Schema Example (schema.json)

```json
{
  "type": "object",
  "properties": {
    "summary": { "type": "string" },
    "issues": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": { "type": "string" },
          "severity": { "type": "string" },
          "count": { "type": "integer" }
        }
      }
    },
    "recommendations": {
      "type": "array",
      "items": { "type": "string" }
    }
  }
}
```

## All CLI Parameters

| Parameter | Required | Default | Description |
|---|---|---|---|
| `--input` | Yes | — | Input file path |
| `--format` | No | `json` | `json` or `text` |
| `--schema-hint` | No | `""` | Field descriptions (json only) |
| `--prompt` | Yes | — | Summarization goal |
| `--output-schema` | Yes | — | JSON Schema file for output |
| `--map-prompt` | No | built-in | Custom MAP system prompt file |
| `--reduce-prompt` | No | built-in | Custom REDUCE system prompt file |
| `--compress-prompt` | No | built-in | Custom compress prompt file |
| `--model` | No | `default` | LLM model name |
| `--api-base` | No | `http://localhost:8000` | OpenAI-compatible API base |
| `--api-key` | No | `sk-placeholder` | API key |
| `--output` | No | stdout | Output file |
| `--map-concurrency` | No | `5` | Parallel MAP workers |
| `--token-budget` | No | `6000` | Max tokens per MAP chunk |
| `--context-tokens` | No | `32000` | Model context window size |
| `--max-reduce-rounds` | No | `20` | Max REDUCE iterations |

## Environment Variables

`LLM_MODEL`, `LLM_API_BASE`, `LLM_API_KEY` — override CLI defaults.

## How It Works

1. **Load** — reads input file into list of strings
2. **Chunk** — splits by token budget (chars ÷ 3)
3. **MAP** — each chunk → LLM → partial JSON result (parallel)
4. **REDUCE** — tree-merge partials until 1 result remains
5. **Output** — final JSON written to file or stdout

Large files that don't fit in one LLM call are automatically split, processed in chunks, and merged. If a merge group is too large, it's split in half. If still too large, items are compressed via LLM. If compression fails, programmatic merge is used as fallback.
```

File: `README.md`

- [ ] **Step 2: Create CLAUDE.md**

```markdown
# CLAUDE.md — General Summarizer Code Guide

## Project Structure

```
summarizer/
  config.py      — PipelineConfig dataclass (all settings in one place)
  loader.py      — load(path, format) → list[str]
  chunker.py     — chunk(rows, budget) → list[list[str]], estimate_tokens(s) → int
  llm_client.py  — LLMClient.call(system, user, schema) → dict (async)
                   Raises: ContextOverflowError, LLMUnavailableError
  pipeline.py    — Pipeline(config).run(rows) → dict (async)
                   _run_map() → parallel MAP
                   _run_reduce() → tree-REDUCE loop
                   _merge_group() → single merge with full error handling
                   _compress() → LLM compression
                   _programmatic_merge() → fallback, no LLM
  main.py        — argparse CLI, loads files, creates config, runs pipeline
  prompts/
    map_default.txt      — MAP system prompt template
    reduce_default.txt   — REDUCE system prompt template
    compress_default.txt — compress prompt template
tests/
  test_loader.py    — loader unit tests
  test_chunker.py   — chunker unit tests
  test_llm_client.py — LLMClient tests (LLM mocked)
  test_pipeline.py  — pipeline tests (LLM mocked)
```

## Key Design Decisions

**Token estimation:** `chars // 3` — cheap, no tokenizer dependency.

**LLM calls:** AsyncOpenAI with SSL verification disabled (`httpx.AsyncClient(verify=False)`) — for internal/self-hosted deployments.

**JSON Schema output:** Schema included in system prompt. `response_format={"type": "json_object"}` forces JSON output. No Pydantic model needed at runtime.

**REDUCE error handling (in order):**
1. ContextOverflowError + group > 2 → split in half, merge each half, merge results
2. ContextOverflowError + pair → compress items one by one until merge fits
3. LLMUnavailableError + 502/503 → wait 30s, retry once
4. LLMUnavailableError + other → compress all items, retry up to 5 times
5. All retries exhausted → `_programmatic_merge()` (no LLM, concatenate arrays)

**Prompt placeholders:** filled via `str.format_map()`. MAP uses `{user_prompt}`, `{schema_hint}`, `{output_schema}`. REDUCE uses `{user_prompt}`, `{output_schema}`. Compress has no placeholders.

## Adding a New Input Format

1. Add a branch in `loader.py` `load()` for the new format string
2. Add tests in `tests/test_loader.py`
3. Update `--format` choices in `main.py`

## Changing Prompt Templates

Default prompts live in `summarizer/prompts/*.txt`. Users can override at runtime with `--map-prompt`, `--reduce-prompt`, `--compress-prompt`. All MAP/REDUCE prompts support the placeholders listed above.

## Running Tests

```bash
pytest tests/ -v
```
```

File: `CLAUDE.md`

- [ ] **Step 3: Create PROMPT_GUIDE.md**

```markdown
# PROMPT_GUIDE.md — Writing Prompts for General Summarizer

## Overview

General Summarizer uses three prompt templates:
- **MAP** — analyzes one chunk of data, produces partial result
- **REDUCE** — merges multiple partial results into one
- **COMPRESS** — shrinks a result when it's too large to fit in context

All prompts are filled using Python's `str.format_map()`.

---

## Placeholders

### MAP prompt (`--map-prompt`)

| Placeholder | What it contains |
|---|---|
| `{user_prompt}` | Your `--prompt` text |
| `{schema_hint}` | Your `--schema-hint` text (empty if not provided) |
| `{output_schema}` | Full JSON Schema as string |

The chunk content is passed as the **user message** automatically — do NOT include `{chunk_content}` in the system prompt.

### REDUCE prompt (`--reduce-prompt`)

| Placeholder | What it contains |
|---|---|
| `{user_prompt}` | Your `--prompt` text |
| `{output_schema}` | Full JSON Schema as string |

The partial results are passed as the **user message** automatically.

### COMPRESS prompt (`--compress-prompt`)

No placeholders. The item to compress is passed as the user message.

---

## Output Schema (schema.json)

Use standard JSON Schema. The LLM will try to conform to it.

### Example: Log analysis

```json
{
  "type": "object",
  "properties": {
    "summary": { "type": "string", "description": "2-3 sentence overview" },
    "top_issues": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": { "type": "string" },
          "severity": { "type": "string", "enum": ["critical", "high", "medium", "low"] },
          "occurrences": { "type": "integer" },
          "recommendation": { "type": "string" }
        }
      }
    }
  }
}
```

### Example: Customer feedback analysis

```json
{
  "type": "object",
  "properties": {
    "overall_sentiment": { "type": "string", "enum": ["positive", "neutral", "negative"] },
    "themes": {
      "type": "array",
      "items": { "type": "string" }
    },
    "urgent_issues": {
      "type": "array",
      "items": { "type": "string" }
    },
    "positive_highlights": {
      "type": "array",
      "items": { "type": "string" }
    }
  }
}
```

---

## Tips

1. **Keep arrays in your schema** — arrays merge cleanly across REDUCE rounds (items are deduplicated).
2. **Avoid deeply nested objects** — the programmatic fallback merge works best with flat or 1-level-deep schemas.
3. **Use `description` fields in schema** — the LLM reads them and produces better output.
4. **Set `--token-budget`** based on your model's context: for 32k context, 6000 is safe; for 128k, you can use 20000-30000.
5. **`--schema-hint` matters for JSON input** — tell the LLM what each field means: `"timestamp: event time ISO8601, level: ERROR/WARN/INFO, msg: log message text"`.

---

## Generating a Custom Prompt

Ask an LLM:

```
I'm using a tool called General Summarizer. It needs a MAP system prompt template.
The prompt will analyze chunks of [describe your data] and produce partial results.
User goal: [your summarization goal].
Output JSON Schema: [paste your schema].
Available placeholders: {user_prompt}, {schema_hint}, {output_schema}.
The chunk content comes as the user message — don't include it in the system prompt.
Write a concise, effective system prompt.
```
```

File: `PROMPT_GUIDE.md`

- [ ] **Step 4: Run full test suite to confirm everything works**

```bash
cd /home/oleg/Documents/general-summarizer
python -m pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md PROMPT_GUIDE.md
git commit -m "docs: add README, CLAUDE.md, PROMPT_GUIDE.md"
```

---

## Self-Review

**Spec coverage check:**
- ✅ loader (json + text)
- ✅ chunker (token-based)
- ✅ LLMClient (async, SSL disabled, ContextOverflowError, LLMUnavailableError)
- ✅ MAP phase (parallel, semaphore, prompt with placeholders)
- ✅ REDUCE phase (adaptive group size, tree-merge)
- ✅ Compression (_maybe_compress, _compress, _compress_and_merge)
- ✅ ContextOverflowError: group>2 splits, pair compresses
- ✅ LLMUnavailableError: 502 waits, timeout compresses, max retries → programmatic fallback
- ✅ Programmatic fallback (_programmatic_merge: arrays concat, strings join, scalars from first)
- ✅ User-overridable prompts (all 3 prompt types)
- ✅ CLI with all parameters from spec
- ✅ README.md, CLAUDE.md, PROMPT_GUIDE.md

**Type consistency check:**
- `chunk()` returns `list[list[str]]` ✅ used correctly in `_run_map`
- `_merge_group(group: list[dict])` ✅ consistent across all callers
- `_compress(item: dict) -> dict` ✅ consistent
- `_programmatic_merge(items: list[dict]) -> dict` ✅ consistent
