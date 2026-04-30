# CLAUDE.md — General Summarizer Code Guide

## Project Structure

```
summarizer/
  config.py       — PipelineConfig dataclass (all settings in one place)
  loader.py       — load(path, format) → list[str]
  chunker.py      — chunk(rows, budget) → list[list[str]]
                    estimate_tokens(s) → int  (chars // 2)
  llm_client.py   — LLMClient (async)
                    .call(system, user, schema) → dict   ← STRUCTURED mode
                    .call_text(system, user) → str       ← FREE mode
                    Raises: ContextOverflowError, LLMUnavailableError
  log.py          — setup(log_file, level), get(name) → Logger
                    SEP / SEP2 separators for formatted output
  pipeline.py     — Pipeline(config).run(rows) → dict | str
                    STRUCTURED: _run_map / _run_reduce (dict path)
                    FREE:       _run_map_text / _run_reduce_text (str path)
                    _merge_group()         — single REDUCE merge + full error handling
                    _compress_and_merge()  — compress one-by-one until fits
                    _compress()            — LLM compression (targets 50% reduction)
                    _maybe_compress()      — compress result if > 30% of context
                    _programmatic_merge()  — fallback, no LLM
                    _save_reduce_checkpoint() / _load_reduce_checkpoint()
  main.py         — argparse CLI entry point
  prompts/
    map_default.txt       — MAP system prompt template
    reduce_default.txt    — REDUCE system prompt template
    compress_default.txt  — compress prompt template
tests/
  test_config.py    — PipelineConfig defaults + auto-derived fields
  test_loader.py    — loader unit tests
  test_chunker.py   — chunker + estimate_tokens
  test_llm_client.py — LLMClient (mocked _create)
  test_pipeline.py   — full pipeline (mocked llm.call), 9 tests
examples/
  k8s_logs/summarize.py  — reference example with OutputMode/ReportFormat enums
```

---

## Key Design Decisions

### Token estimation

`chars // 2` — conservative estimate for JSON/log data (JSON with timestamps, numbers, special chars tokenizes at ~1.8–2 chars/token, not 3). Using a more conservative estimate prevents context overflow.

### Context budget (auto-derived from one number)

`PipelineConfig` takes a single `context_tokens`. `__post_init__` derives:
- `max_output_tokens = min(32768, context * 0.30)` — or caller-specified value
- `token_budget = context - max_output_tokens - 3000` — data budget for MAP chunks

`_reduce_budget_tokens()` uses the same formula for REDUCE group sizing.

### Two output modes

**STRUCTURED** (`output_mode="json"`):
- `LLMClient.call()` wraps user JSON Schema in a dynamic Pydantic `RootModel` with `jsonschema` validation
- Instructor handles retry on invalid JSON / schema mismatch
- MAP and REDUCE return `dict`

**FREE** (`output_mode="text"`):
- `LLMClient.call_text()` — raw OpenAI call, no instructor, no schema
- MAP returns `list[str]`, REDUCE merges text blocks
- Result saved as `.txt`

### Prompt safety

All `str.format_map()` calls use `_SafeDict` which returns `{key}` for unknown placeholders instead of raising `KeyError`. User prompts can contain literal `{...}` (JSON examples etc.) safely.

### LLM error handling

```
BadRequestError (400):
  → overflow keywords → ContextOverflowError  (triggers split/compress)
  → other            → LLMUnavailableError    (no crash)

RateLimitError (429)   → sleep retry_wait_seconds, retry
APITimeoutError        → retry immediately (no wait)
APIConnectionError     → retry immediately
APIStatusError 5xx     → sleep retry_wait_seconds, retry
APIStatusError other   → LLMUnavailableError (no crash)

InstructorRetryException:
  → overflow keywords → ContextOverflowError
  → rate limit / 429  → sleep retry_wait_seconds, retry
  → timeout           → retry immediately
  → other             → LLMUnavailableError
```

`max_retries = -1` means infinite retries. `retry_wait_seconds` is flat (not exponential).

### REDUCE overflow cascade (in order)

1. **Pre-compress**: if group payload > `_reduce_budget_tokens()` → compress all items before merge
2. **Overflow on merge** → compress all items, retry merge
3. **Still overflow + group > 2** → split in half, merge each half recursively, merge results
4. **Still overflow on pair** → `_compress_and_merge` (compress one-by-one until fits)
5. **All retries exhausted** → `_programmatic_merge` (no LLM)

### Artifact directory & resume

Every `Pipeline.__init__` creates `runs/{timestamp}/` with subdirs `map/`, `reduce/`, `llm/`.

**MAP**: each chunk saved to `map/chunk_NNN.json` immediately after computation. On resume (`resume_run`), existing files are loaded instead of re-computing.

**REDUCE**: each merged group saved to `reduce/round_RR_group_GG.json`. After every round, `reduce/checkpoint.json` is written with `{"round": N, "items": [...]}`. On resume, checkpoint is loaded and processing continues from that round; already-saved group files are loaded and skipped.

**LLM audit**: every call saves `llm/call_NNNN_system.txt`, `llm/call_NNNN_user.txt`, `llm/call_NNNN_response.txt`.

### Compression behavior

`_compress(item)` appends to the compress prompt:
> "Target size: approximately N tokens (half of current M tokens)."

Always targets 50% reduction. `_maybe_compress(item)` triggers compression when `estimate_tokens(item) > context * 0.30`.

### Programmatic merge (fallback)

Schema-agnostic, key-by-key:
- `list` fields: deduplicated by JSON repr, concatenated
- `str` fields: joined with `\n---\n`
- `int`/`float`/`bool`: first item's value

---

## Adding a New Input Format

1. Add branch in `loader.py → load()` for the new format string
2. Add tests in `tests/test_loader.py`
3. Update `--format` choices in `main.py`

## Changing Prompt Templates

Defaults in `summarizer/prompts/*.txt`. Override at runtime: `--map-prompt`, `--reduce-prompt`, `--compress-prompt` (CLI) or `map_prompt_template=...` (PipelineConfig).

Placeholders are filled with `_SafeDict` — unknown `{keys}` pass through unchanged.

## Running Tests

```bash
pytest tests/ -v
```

Pipeline tests use `runs_dir=None` to avoid creating artifact directories.
