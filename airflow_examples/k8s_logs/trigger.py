"""Запуск суммаризации k8s логов через Airflow API.

1. Забирает логи из ClickHouse (контейнеры + k8s events)
2. Кладёт input.json и schema.json в /opt/airflow/data/
3. Триггерит DAG general_summarizer через Airflow REST API
4. Ждёт завершения и печатает результат

Настрой параметры в секции CONFIG и запусти:
    python airflow_examples/k8s_logs/trigger.py
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────

PERIOD_START = "2025-04-01T09:00:00"
PERIOD_END   = "2025-04-01T10:00:00"
INCIDENT     = "Airflow workers failing on ndp-p01. Tasks hanging, ImagePullBackOff on several pods."

CH_HOST     = "localhost"
CH_PORT     = 8123
CH_USER     = "default"
CH_PASSWORD = ""
CH_DATABASE = "default"
MAX_ROWS    = 5000

AIRFLOW_BASE_URL = os.getenv("AIRFLOW_BASE_URL", "http://localhost:8080")
AIRFLOW_USER     = os.getenv("AIRFLOW_USER",     "airflow")
AIRFLOW_PASSWORD = os.getenv("AIRFLOW_PASSWORD", "airflow")
DAG_ID           = os.getenv("AIRFLOW_DAG_ID",   "general_summarizer")

# Директория, примонтированная в контейнер как /data
DATA_DIR = Path("/opt/airflow/data")

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

# ── ClickHouse ────────────────────────────────────────────────────────────────

def ch_query(sql: str) -> list:
    url = f"http://{CH_HOST}:{CH_PORT}/"
    body = (sql + " FORMAT JSONEachRow").encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("X-ClickHouse-User", CH_USER)
    req.add_header("X-ClickHouse-Key", CH_PASSWORD)
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    with urllib.request.urlopen(req, timeout=120) as resp:
        lines = resp.read().decode("utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]


SQL_CONTAINERS = f"""
SELECT
    min(timestamp)  AS timestamp,
    max(timestamp)  AS end_time,
    count()         AS cnt,
    any(kubernetes_namespace_name)  AS namespace,
    any(kubernetes_pod_name)        AS pod_name,
    any(kubernetes_container_name)  AS container_name,
    min(log)        AS log_text
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
ORDER BY timestamp ASC
LIMIT {MAX_ROWS}
"""

SQL_EVENTS = f"""
SELECT
    timestamp,
    timestamp          AS end_time,
    reason,
    involvedObject_namespace AS namespace,
    involvedObject_name      AS object_name,
    message
FROM {CH_DATABASE}.log_k8s_events
WHERE timestamp > parseDateTime64BestEffort('{PERIOD_START}')
  AND timestamp <= parseDateTime64BestEffort('{PERIOD_END}')
ORDER BY timestamp ASC
LIMIT {MAX_ROWS}
"""

# ── Airflow API ───────────────────────────────────────────────────────────────

def _airflow_request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{AIRFLOW_BASE_URL}/api/v1{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)

    credentials = f"{AIRFLOW_USER}:{AIRFLOW_PASSWORD}"
    import base64
    token = base64.b64encode(credentials.encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def trigger_dag(conf: dict) -> str:
    result = _airflow_request("POST", f"/dags/{DAG_ID}/dagRuns", {"conf": conf})
    return result["dag_run_id"]


def wait_for_dag(dag_run_id: str, poll_interval: int = 15) -> str:
    print(f"Waiting for dag_run_id={dag_run_id} ...", file=sys.stderr)
    while True:
        result = _airflow_request("GET", f"/dags/{DAG_ID}/dagRuns/{dag_run_id}")
        state = result["state"]
        print(f"  state: {state}", file=sys.stderr)
        if state in ("success", "failed"):
            return state
        time.sleep(poll_interval)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # 1. Забираем данные из ClickHouse
    print("Fetching container logs from ClickHouse...", file=sys.stderr)
    containers = ch_query(SQL_CONTAINERS)
    print(f"  {len(containers)} rows", file=sys.stderr)

    print("Fetching k8s events from ClickHouse...", file=sys.stderr)
    events = ch_query(SQL_EVENTS)
    print(f"  {len(events)} rows", file=sys.stderr)

    all_rows = sorted(containers + events, key=lambda r: r.get("timestamp", ""))
    print(f"Total: {len(all_rows)} rows", file=sys.stderr)

    # 2. Кладём файлы в DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    input_path  = DATA_DIR / "k8s_input.json"
    schema_path = DATA_DIR / "k8s_schema.json"
    output_path = DATA_DIR / "k8s_output.json"

    input_path.write_text(json.dumps(all_rows, ensure_ascii=False), encoding="utf-8")
    print(f"Input saved → {input_path}", file=sys.stderr)

    schema_src = Path(__file__).parent / "schema.json"
    schema_path.write_text(schema_src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Schema saved → {schema_path}", file=sys.stderr)

    # 3. Триггерим DAG
    user_prompt = (
        f"Incident: {INCIDENT} "
        f"Period: {PERIOD_START} → {PERIOD_END}. "
        "Find root causes, key events, recommendations."
    )

    conf = {
        "input_path":         "/data/k8s_input.json",
        "input_format":       "json",
        "output_mode":        "json",
        "prompt":             user_prompt,
        "output_schema_path": "/data/k8s_schema.json",
        "output_path":        "/data/k8s_output.json",
        "schema_hint":        SCHEMA_HINT,
        "map_concurrency":    3,
        "token_budget":       6000,
        "context_tokens":     32000,
    }

    print(f"\nTriggering DAG '{DAG_ID}'...", file=sys.stderr)
    dag_run_id = trigger_dag(conf)
    print(f"dag_run_id: {dag_run_id}", file=sys.stderr)

    # 4. Ждём завершения
    state = wait_for_dag(dag_run_id)

    if state != "success":
        print(f"\nDAG failed (state={state})", file=sys.stderr)
        sys.exit(1)

    # 5. Читаем и печатаем результат
    if output_path.exists():
        result = json.loads(output_path.read_text(encoding="utf-8"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("ERROR: output file not found", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
