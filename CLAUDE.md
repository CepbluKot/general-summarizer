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
                   _compress_and_merge() → compress one-by-one until fits
                   _compress() → LLM compression
                   _programmatic_merge() → fallback, no LLM
  main.py        — argparse CLI, loads files, creates config, runs pipeline
  prompts/
    map_default.txt      — MAP system prompt template
    reduce_default.txt   — REDUCE system prompt template
    compress_default.txt — compress prompt template
tests/
  test_config.py    — PipelineConfig dataclass tests
  test_loader.py    — loader unit tests
  test_chunker.py   — chunker unit tests
  test_llm_client.py — LLMClient tests (LLM mocked)
  test_pipeline.py   — pipeline tests (LLM mocked, 9 tests)
```

## Key Design Decisions

**Token estimation:** `chars // 3` — cheap, no tokenizer dependency.

**LLM calls:** AsyncOpenAI with SSL verification disabled (`httpx.AsyncClient(verify=False)`) — for internal/self-hosted deployments.

**JSON Schema output:** User schemas stay as plain JSON Schema dicts. `LLMClient` wraps each schema in a dynamic Pydantic `RootModel` whose validator runs `jsonschema` against the original schema, then passes that model to `instructor` as `response_model`. Instructor handles parsing retries and schema-validation retries; callers still receive a plain `dict`.

**REDUCE error handling (in order):**
1. ContextOverflowError + group > 2 → split in half, merge each half, merge results
2. ContextOverflowError + pair → compress items one by one until merge fits (`_compress_and_merge`)
3. LLMUnavailableError + 502/503 → wait 30s, retry once
4. LLMUnavailableError + other → compress all items, retry up to `_MAX_COMPRESS_RETRIES=5` times
5. All retries exhausted → `_programmatic_merge()` (no LLM, concatenate arrays)

**Prompt placeholders:** filled via `str.format_map()`. MAP uses `{user_prompt}`, `{schema_hint}`, `{output_schema}`. REDUCE uses `{user_prompt}`, `{output_schema}`. Compress has no placeholders.

**Programmatic merge rules:**
- Arrays: deduplicated by JSON repr, concatenated
- Strings: joined with `\n---\n`
- Numbers/bools: first item's value

## Adding a New Input Format

1. Add a branch in `loader.py` `load()` for the new format string
2. Add tests in `tests/test_loader.py`
3. Update `--format` choices in `main.py`

## Changing Prompt Templates

Default prompts live in `summarizer/prompts/*.txt`. Users can override at runtime with `--map-prompt`, `--reduce-prompt`, `--compress-prompt`.

## Running Tests

```bash
pytest tests/ -v
```
