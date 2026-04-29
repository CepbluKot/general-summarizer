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
