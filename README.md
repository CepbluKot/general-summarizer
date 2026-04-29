# General Summarizer

CLI tool that MAP-REDUCEs any large JSON or text file through an OpenAI-compatible LLM and returns a structured JSON result defined by your JSON Schema.

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

The output schema is sent in the prompt and wrapped as an Instructor `response_model` at runtime. Instructor performs parsing/validation retries, while the user-facing schema format remains standard JSON Schema.
