# General Summarizer

CLI tool that MAP-REDUCEs any large JSON or plain-text file through an OpenAI-compatible LLM. Supports two output modes: **STRUCTURED** (JSON Schema + instructor validation) and **FREE** (raw text, LLM decides format).

## Install

```bash
pip install -r requirements.txt
```

## Quick Start

### Via Python script (recommended)

Edit `examples/k8s_logs/summarize.py`, set CONFIG variables, run:

```bash
python examples/k8s_logs/summarize.py
```

Results are saved to `runs/{timestamp}/result.json` (or `.txt` in FREE mode). Run directory is logged at the end.

### Via CLI

```bash
python -m summarizer.main \
  --input data.json \
  --format json \
  --schema-hint "id: record id, message: event text, level: severity" \
  --prompt "Find the top 5 issues grouped by severity" \
  --output-schema schema.json \
  --model qwen2.5-72b \
  --api-base http://localhost:8000 \
  --api-key sk-your-key \
  --context-tokens 32000
```

---

## Output Modes

### STRUCTURED (default)

LLM output is validated against a JSON Schema using [instructor](https://github.com/jxnl/instructor). Invalid JSON is retried automatically.

```python
OUTPUT_MODE = OutputMode.STRUCTURED
```

Requires `--output-schema schema.json`.

### FREE

No schema, no validation. LLM generates whatever format the prompt describes (markdown, bullet lists, prose, etc.).

```python
OUTPUT_MODE = OutputMode.FREE
```

Output is saved as `.txt`. Schema hint and `{output_schema}` placeholder are ignored.

---

## Context & Token Budget

Set **one number** — the model's total context window. Everything else is derived automatically:

```python
LLM_CONTEXT_TOKENS = 262000   # total context window
LLM_OUTPUT_TOKENS  = 32768    # reserved for model output
# data budget = context - output - ~3k prompt buffer
```

Token estimation uses `chars // 2` (conservative for JSON/log data).

---

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
          "title":    { "type": "string" },
          "severity": { "type": "string", "enum": ["critical","high","medium","low"] },
          "count":    { "type": "integer" }
        }
      }
    },
    "recommendations": { "type": "array", "items": { "type": "string" } }
  }
}
```

---

## All CLI Parameters

| Parameter | Default | Description |
|---|---|---|
| `--input` | required | Input file path |
| `--format` | `json` | `json` or `text` |
| `--schema-hint` | `""` | Field descriptions (json mode) |
| `--prompt` | required | Summarization goal |
| `--output-schema` | required | JSON Schema file (STRUCTURED mode) |
| `--output-mode` | `json` | `json` (STRUCTURED) or `text` (FREE) |
| `--map-prompt` | built-in | Custom MAP system prompt file |
| `--reduce-prompt` | built-in | Custom REDUCE system prompt file |
| `--compress-prompt` | built-in | Custom compress prompt file |
| `--model` | `default` | LLM model name |
| `--api-base` | `http://localhost:8000` | OpenAI-compatible API base URL |
| `--api-key` | `sk-placeholder` | API key |
| `--output` | `None` | Output file (default: saved to runs/) |
| `--context-tokens` | `32000` | Total model context window in tokens |
| `--map-concurrency` | `5` | Parallel MAP LLM calls |
| `--max-reduce-rounds` | `20` | Max REDUCE tree iterations |
| `--max-retries` | `3` | Retries on error (-1 = infinite) |
| `--retry-wait-seconds` | `60` | Wait between retries (rate limit / server error) |
| `--llm-timeout` | `10800` | Single LLM call timeout in seconds (3 hours) |
| `--runs-dir` | `runs` | Artifact directory; `None` = disable |
| `--resume-run` | `None` | Resume a crashed run (folder name in runs/) |

## Environment Variables

`LLM_MODEL`, `LLM_API_BASE`, `LLM_API_KEY` — override CLI defaults.

---

## Artifact Directory

Every run creates `runs/{timestamp}/`:

```
runs/20260430_100000/
  map/
    chunk_000.json    ← MAP result per chunk
    chunk_001.json
    ...
  reduce/
    round_01_group_01.json   ← REDUCE merge per group
    checkpoint.json          ← REDUCE state (for resume)
  llm/
    call_0001_system.txt     ← system prompt of each LLM call
    call_0001_user.txt       ← user message
    call_0001_response.txt   ← raw LLM response
    ...
  result.json                ← final output
```

Disable with `--runs-dir ""` or `runs_dir=None`.

---

## Resume After Crash

If a run crashes mid-way, resume from where it stopped:

```python
RESUME_RUN = "20260430_100000"   # folder name from runs/
```

- **MAP**: already-computed chunks are loaded from files, not re-sent to LLM
- **REDUCE**: resumes from last saved checkpoint

---

## How It Works

1. **Load** — reads input file into list of strings (one per JSON object or text line)
2. **Chunk** — splits by token budget (`chars // 2`, conservative estimate)
3. **MAP** — each chunk → LLM in parallel → partial result (JSON dict or text)
4. **REDUCE** — tree-merge: group by adaptive size → LLM merge → repeat until 1 result
5. **Output** — saved to `runs/{timestamp}/result.json` (or `.txt`)

### Overflow handling

- **MAP chunk too large** → split in half recursively (up to depth 8)
- **REDUCE group too large** → pre-compress all items, then merge; if still overflows → split in half
- **Pair can't merge** → compress one by one until it fits (`_compress_and_merge`)
- **All LLM retries exhausted** → programmatic merge (array concat, string join) — never crashes

### Retry policy

| Error | Action |
|---|---|
| 429 Rate Limit | wait `retry_wait_seconds`, retry |
| Timeout / Connection | retry immediately |
| 500 / 502 / 503 / 504 | wait `retry_wait_seconds`, retry |
| 400 non-overflow | log error, raise `LLMUnavailableError` |
| Context overflow | `ContextOverflowError` → split/compress |
