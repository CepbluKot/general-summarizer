"""Суммаризация k8s логов из ClickHouse.

Настрой параметры в секции CONFIG и запусти:
    python examples/k8s_logs/summarize.py
"""
import asyncio
import json
import sys
import urllib.request
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────

PERIOD_START  = "2025-04-01T09:00:00"
PERIOD_END    = "2025-04-01T10:00:00"

CH_HOST       = "localhost"
CH_PORT       = 8123
CH_USER       = "default"
CH_PASSWORD   = ""
CH_DATABASE   = "default"
MAX_ROWS      = 5000   # сколько строк выгружать из БД (по каждому SQL-запросу)

LLM_API_BASE       = "https://localhost:8000"
LLM_API_KEY        = "sk-placeholder"
LLM_MODEL          = "qwen2.5-72b-instruct"
LLM_CONTEXT_TOKENS = 262000  # полный контекст модели в токенах
LLM_OUTPUT_TOKENS  = 32768   # сколько токенов выделяем на ответ модели
                              # на данные уйдёт: context - output - ~3k на промпт
MAP_CONCURRENCY    = 3       # сколько батчей обрабатывается параллельно
                              # уменьши до 1-2 если получаешь 429 rate limit
MAX_RETRIES        = -1      # попыток при ошибке (-1 = бесконечно)
RETRY_WAIT_SECONDS = 60      # секунд ожидания при rate limit / server error
LLM_TIMEOUT        = 10800   # таймаут одного LLM-вызова в секундах (3 часа)

INCIDENT      = "Airflow workers failing on ndp-p01. Tasks hanging, ImagePullBackOff on several pods."

OUTPUT_FILE   = "examples/k8s_logs/result.json"   # None → stdout
LOG_FILE      = "examples/k8s_logs/run.log"        # None → только stderr

MAP_PROMPT = """You are a senior SRE analyzing a Kubernetes log fragment during an incident.

Task: {user_prompt}

Input field descriptions:
{schema_hint}

Analyze the log fragment and extract key events, anomalies, and hypotheses.
Focus on errors, crashes, timeouts, OOM, and scheduling failures.
This is a PARTIAL analysis — only capture what you see in this fragment.

Output JSON Schema:
{output_schema}

Output ONLY valid JSON matching the schema. No prose, no markdown fences."""

REDUCE_PROMPT = """You are a senior SRE synthesizing partial Kubernetes incident analyses.

Task: {user_prompt}

Merge the partial analyses into one unified report.
Deduplicate events, keep top hypotheses by confidence, merge recommendations.

Output JSON Schema:
{output_schema}

Output ONLY valid JSON matching the schema. No prose, no markdown fences."""

COMPRESS_PROMPT = """Compress the following JSON incident analysis to half its size.
Keep the most critical events, top hypotheses, and all recommendations.
Preserve the exact same JSON structure.

Output ONLY valid JSON. No prose, no markdown fences."""

# ── SQL ───────────────────────────────────────────────────────────────────────

SQL_CONTAINERS = f"""
SELECT
    start_time AS timestamp,
    end_time,
    cnt,
    namespace,
    pod_name,
    container_name,
    log_text
FROM (
    SELECT
        min(timestamp) AS start_time,
        max(timestamp) AS end_time,
        count() AS cnt,
        any(kubernetes_namespace_name) AS namespace,
        any(kubernetes_pod_name) AS pod_name,
        any(kubernetes_container_name) AS container_name,
        min(log) AS log_text
    FROM (
        SELECT *,
            sum(is_new_group) OVER (
                PARTITION BY kubernetes_namespace_name, kubernetes_container_name
                ORDER BY timestamp ASC
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS group_id
        FROM (
            SELECT *,
                if(
                    right(log, 10) != ifNull(lagInFrame(right(log, 10)) OVER (
                        PARTITION BY kubernetes_namespace_name, kubernetes_container_name
                        ORDER BY timestamp ASC
                    ), ''), 1, 0
                ) AS is_new_group
            FROM {CH_DATABASE}.log_k8s_containers
            WHERE timestamp > parseDateTime64BestEffort('{PERIOD_START}')
              AND timestamp <= parseDateTime64BestEffort('{PERIOD_END}')
              AND multiSearchAny(lower(log), [
                    'fatal','critical','error','exception','alert','panic',
                    'failed','failure','crash','abort','timeout','timed out',
                    'deadlock','out of memory','oom','disk full','no space left',
                    'permission denied','access denied','unauthorized','forbidden',
                    'connection refused','connection reset','ssl error','segfault',
                    'killed','rollback','traceback','stack trace'
              ])
            ORDER BY timestamp ASC
        )
    )
    GROUP BY group_id, kubernetes_namespace_name, kubernetes_container_name
)
ORDER BY timestamp ASC
LIMIT {MAX_ROWS}
"""

SQL_EVENTS = f"""
SELECT
    timestamp,
    timestamp AS end_time,
    reason,
    involvedObject_namespace AS namespace,
    involvedObject_name AS object_name,
    message
FROM {CH_DATABASE}.log_k8s_events
WHERE timestamp > parseDateTime64BestEffort('{PERIOD_START}')
  AND timestamp <= parseDateTime64BestEffort('{PERIOD_END}')
ORDER BY timestamp ASC
LIMIT {MAX_ROWS}
"""

# ── OUTPUT SCHEMA ─────────────────────────────────────────────────────────────

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "time_range": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string", "description": "3-5 sentences: what happened"},
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "string"},
                    "source": {"type": "string"},
                    "description": {"type": "string"},
                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]}
                }
            }
        },
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]}
                }
            }
        },
        "recommendations": {"type": "array", "items": {"type": "string"}}
    }
}

SCHEMA_HINT = (
    "timestamp: event time ISO8601, "
    "end_time: event end time, "
    "cnt: number of repeated log lines, "
    "namespace: k8s namespace, "
    "pod_name: pod name, "
    "container_name: container name, "
    "log_text: log message (containers); "
    "reason: k8s event reason, "
    "object_name: affected object, "
    "message: event message (events)"
)

# ── ClickHouse ────────────────────────────────────────────────────────────────

def ch_query(sql):
    url = f"https://{CH_HOST}:{CH_PORT}/"
    body = (sql + " FORMAT JSONEachRow").encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("X-ClickHouse-User", CH_USER)
    req.add_header("X-ClickHouse-Key", CH_PASSWORD)
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    with urllib.request.urlopen(req, timeout=120) as resp:
        lines = resp.read().decode("utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from summarizer.config import PipelineConfig
    from summarizer.pipeline import Pipeline

    print("Fetching container logs...", file=sys.stderr)
    containers = ch_query(SQL_CONTAINERS)
    print(f"  {len(containers)} rows", file=sys.stderr)

    print("Fetching k8s events...", file=sys.stderr)
    events = ch_query(SQL_EVENTS)
    print(f"  {len(events)} rows", file=sys.stderr)

    all_rows = containers + events
    all_rows.sort(key=lambda r: r.get("timestamp", ""))
    rows = [json.dumps(r, ensure_ascii=False, default=str) for r in all_rows]
    print(f"Total: {len(rows)} rows", file=sys.stderr)

    config = PipelineConfig(
        input_path="",
        format="json",
        schema_hint=SCHEMA_HINT,
        user_prompt=f"Incident: {INCIDENT}. Period: {PERIOD_START} → {PERIOD_END}. Find root causes, key events, recommendations.",
        output_schema=OUTPUT_SCHEMA,
        map_prompt_template=MAP_PROMPT,
        reduce_prompt_template=REDUCE_PROMPT,
        compress_prompt_template=COMPRESS_PROMPT,
        model=LLM_MODEL,
        api_base=LLM_API_BASE,
        api_key=LLM_API_KEY,
        output_path=OUTPUT_FILE,
        context_tokens=LLM_CONTEXT_TOKENS,
        max_output_tokens=LLM_OUTPUT_TOKENS,
        map_concurrency=MAP_CONCURRENCY,
        max_retries=MAX_RETRIES,
        retry_wait_seconds=RETRY_WAIT_SECONDS,
        llm_timeout=LLM_TIMEOUT,
        log_file=LOG_FILE,
    )

    pipeline = Pipeline(config)
    result = await pipeline.run(rows)

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if OUTPUT_FILE:
        Path(OUTPUT_FILE).write_text(output, encoding="utf-8")
        print(f"Result → {OUTPUT_FILE}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    asyncio.run(main())
