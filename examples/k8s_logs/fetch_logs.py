"""Выгрузка k8s логов из ClickHouse в JSON-файл для general-summarizer.

Использование:
    python fetch_logs.py \
        --start "2025-04-01T09:00:00" \
        --end   "2025-04-01T10:00:00" \
        --ch-host localhost \
        --ch-port 8123 \
        --ch-user default \
        --ch-password "" \
        --ch-database default \
        --queries 0,1 \
        --max-rows 5000 \
        --output logs.json
"""
import argparse
import json
import sys
import urllib.request
from datetime import datetime


# ── SQL-шаблоны ──────────────────────────────────────────────────────────────
# Плейсхолдеры: {database}, {period_start}, {period_end}, {limit}

SQL_QUERIES = [
    # 0: container logs — ошибки, сгруппированные по повторяющимся строкам
    """
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
                FROM {database}.log_k8s_containers
                WHERE timestamp > parseDateTime64BestEffort('{period_start}')
                  AND timestamp <= parseDateTime64BestEffort('{period_end}')
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
    LIMIT {limit}
    """,

    # 1: k8s events
    """
    SELECT
        timestamp,
        timestamp AS end_time,
        reason,
        involvedObject_namespace AS namespace,
        involvedObject_name AS object_name,
        message
    FROM {database}.log_k8s_events
    WHERE timestamp > parseDateTime64BestEffort('{period_start}')
      AND timestamp <= parseDateTime64BestEffort('{period_end}')
    ORDER BY timestamp ASC
    LIMIT {limit}
    """,
]


def ch_query(host, port, user, password, sql, timeout=120):
    url = f"http://{host}:{port}/"
    body = (sql + " FORMAT JSONEachRow").encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("X-ClickHouse-User", user)
    req.add_header("X-ClickHouse-Key", password)
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            lines = resp.read().decode("utf-8").splitlines()
            return [json.loads(line) for line in lines if line.strip()]
    except urllib.request.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ClickHouse HTTP {e.code}: {body_text[:500]}") from e


def main():
    p = argparse.ArgumentParser(description="Fetch k8s logs from ClickHouse")
    p.add_argument("--start", required=True, help="Period start, ISO 8601")
    p.add_argument("--end", required=True, help="Period end, ISO 8601")
    p.add_argument("--ch-host", default="localhost")
    p.add_argument("--ch-port", type=int, default=8123)
    p.add_argument("--ch-user", default="default")
    p.add_argument("--ch-password", default="")
    p.add_argument("--ch-database", default="default")
    p.add_argument("--queries", default="0,1", help="Comma-separated SQL query indices (0=containers, 1=events)")
    p.add_argument("--max-rows", type=int, default=5000)
    p.add_argument("--output", default="logs.json")
    args = p.parse_args()

    start_dt = datetime.fromisoformat(args.start)
    end_dt = datetime.fromisoformat(args.end)
    if (end_dt - start_dt).total_seconds() > 7 * 24 * 3600:
        print("ERROR: period > 7 days", file=sys.stderr)
        sys.exit(1)

    indices = [int(i.strip()) for i in args.queries.split(",") if i.strip()]

    all_rows = []
    for idx in indices:
        if idx < 0 or idx >= len(SQL_QUERIES):
            print(f"ERROR: query index {idx} out of range", file=sys.stderr)
            sys.exit(1)
        sql = SQL_QUERIES[idx].format(
            database=args.ch_database,
            period_start=args.start,
            period_end=args.end,
            limit=args.max_rows,
        )
        rows = ch_query(args.ch_host, args.ch_port, args.ch_user, args.ch_password, sql)
        all_rows.extend(rows)
        print(f"Query {idx}: {len(rows)} rows", file=sys.stderr)

    all_rows.sort(key=lambda r: r.get("timestamp", ""))
    all_rows = all_rows[:args.max_rows]

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=2, default=str)

    print(f"Saved {len(all_rows)} rows → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
