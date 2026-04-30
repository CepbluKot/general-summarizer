# PROMPT_GUIDE.md — Writing Prompts for General Summarizer

## Overview

General Summarizer uses three prompt templates:
- **MAP** — analyzes one data chunk, returns partial result
- **REDUCE** — merges partial results into one final result
- **COMPRESS** — shrinks a result that's too large to fit in context

All prompts are filled via `str.format_map()` with a safe dict — unknown `{keys}` pass through unchanged, so you can safely include JSON examples with literal `{...}` in your prompts.

---

## Output Modes

### STRUCTURED mode (`output_mode="json"`)

LLM output is validated against your JSON Schema. Instructor retries automatically on invalid JSON.

- `{output_schema}` placeholder is filled with your schema as a JSON string
- Output is always a dict conforming to the schema

### FREE mode (`output_mode="text"`)

No schema, no validation. LLM generates whatever the prompt describes.

- `{output_schema}` is empty string — you can omit it from your prompt
- Output is plain text (markdown, bullet lists, prose, etc.)
- Ideal for narrative reports where structure varies

---

## Placeholders

### MAP prompt

| Placeholder | What it contains |
|---|---|
| `{user_prompt}` | Your summarization goal (`--prompt`) |
| `{schema_hint}` | Field descriptions (`--schema-hint`); empty string if not provided |
| `{output_schema}` | JSON Schema as string (empty in FREE mode) |

**Important:** chunk content is passed as the **user message** automatically — do NOT put it in the system prompt.

### REDUCE prompt

| Placeholder | What it contains |
|---|---|
| `{user_prompt}` | Your summarization goal |
| `{output_schema}` | JSON Schema as string (empty in FREE mode) |

Partial results are passed as the **user message** automatically (numbered: `### Partial 1`, `### Partial 2`, ...).

### COMPRESS prompt

No placeholders. The item to compress is the user message. The pipeline appends:
> "Target size: approximately N tokens (half of current M tokens)."

---

## Writing Effective Prompts

### STRUCTURED mode tips

1. **Repeat the schema in plain English** — "Return events as a list of objects with timestamp, source, description, severity" helps more than just the schema.
2. **End with explicit JSON instruction** — "Output ONLY valid JSON matching the schema. No prose, no markdown fences."
3. **For REDUCE**: tell the LLM how to merge — "Deduplicate events by source+description, keep top hypotheses by confidence."

### FREE mode tips

1. **Specify the exact format you want** — "Write a markdown report with: ## Summary, ## Key Events (bullet list with timestamps), ## Recommendations."
2. **For REDUCE**: tell the LLM how to synthesize — "Merge the partial analyses into a single coherent report. Keep the most critical findings from each part."
3. **Be explicit about language** — "Write in Russian. Keep technical terms (pod names, namespaces) as-is."

---

## JSON Schema Design

Use standard [JSON Schema](https://json-schema.org/). Tips:

### Keep arrays at the top level

Arrays merge cleanly across REDUCE rounds (deduplicated by JSON repr). Nested objects inside arrays are preserved.

```json
{
  "type": "object",
  "properties": {
    "summary": { "type": "string" },
    "events": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "timestamp":   { "type": "string" },
          "source":      { "type": "string" },
          "description": { "type": "string" },
          "severity":    { "type": "string", "enum": ["critical","high","medium","low","info"] }
        }
      }
    },
    "recommendations": { "type": "array", "items": { "type": "string" } }
  }
}
```

### Use `description` fields

The LLM reads them and produces better output:

```json
"summary": {
  "type": "string",
  "description": "3-5 sentences: what happened, which services affected, approximate impact"
}
```

### Avoid deeply nested objects in programmatic fallback

If REDUCE falls back to programmatic merge (LLM unavailable), deeply nested objects are merged by first-value. Keep critical data in arrays or flat fields.

---

## Generating Prompts with an LLM

### MAP prompt

```
I'm using General Summarizer, a MAP-REDUCE tool. I need a MAP system prompt.

The MAP phase analyzes one CHUNK of data and returns a PARTIAL result.
Data type: [describe your data]
User goal: [what you want to find]
Output JSON Schema: [paste schema]

Available placeholders: {user_prompt}, {schema_hint}, {output_schema}
The chunk content arrives as the USER message — don't include it in the system prompt.

Write a concise, effective system prompt. End with:
"Output ONLY valid JSON matching the schema. No prose, no markdown fences."
```

### REDUCE prompt

```
I need a REDUCE system prompt for General Summarizer.

The REDUCE phase MERGES multiple partial analyses into one unified result.
User goal: [what you want to find]
Output JSON Schema: [paste schema]

Available placeholders: {user_prompt}, {output_schema}
The partial results arrive as the USER message in numbered blocks.

Write a concise merge prompt. Include instructions to deduplicate and synthesize.
```

### FREE mode report prompt

```
I need a MAP prompt for General Summarizer in FREE text mode (no JSON schema).
The output should be: [describe desired format — markdown, bullet list, etc.]
Data type: [describe your data]
Goal: [what you want to find]

Placeholder available: {user_prompt}, {schema_hint}
Write a system prompt that produces well-structured [format] output.
```

---

## Example: k8s Incident Analysis

### Schema

```json
{
  "type": "object",
  "properties": {
    "time_range": { "type": "array", "items": { "type": "string" } },
    "summary": { "type": "string", "description": "3-5 sentences: what happened" },
    "events": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "timestamp":   { "type": "string" },
          "source":      { "type": "string" },
          "description": { "type": "string" },
          "severity":    { "type": "string", "enum": ["critical","high","medium","low","info"] }
        }
      }
    },
    "hypotheses": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title":       { "type": "string" },
          "description": { "type": "string" },
          "confidence":  { "type": "string", "enum": ["low","medium","high"] }
        }
      }
    },
    "recommendations": { "type": "array", "items": { "type": "string" } }
  }
}
```

### MAP prompt

```
You are a senior SRE analyzing a Kubernetes log fragment during an incident.

Task: {user_prompt}

Input field descriptions:
{schema_hint}

Analyze the log fragment and extract key events, anomalies, and hypotheses.
Focus on errors, crashes, timeouts, OOM, and scheduling failures.
This is a PARTIAL analysis — only capture what is visible in this fragment.

Output JSON Schema:
{output_schema}

Output ONLY valid JSON matching the schema. No prose, no markdown fences.
```

### REDUCE prompt

```
You are a senior SRE synthesizing partial Kubernetes incident analyses.

Task: {user_prompt}

Merge the partial analyses into one unified report.
Deduplicate events by (timestamp + source + description).
Keep the top 5 hypotheses by confidence. Merge all recommendations.

Output JSON Schema:
{output_schema}

Output ONLY valid JSON matching the schema. No prose, no markdown fences.
```
