#!/usr/bin/env bash
# Полный pipeline: выгрузка логов из ClickHouse → суммаризация → результат
#
# Настрой переменные под свой стенд и запусти:
#   bash run.sh

set -euo pipefail

# ── Настройки ──────────────────────────────────────────────────────────────────

PERIOD_START="2025-04-01T09:00:00"
PERIOD_END="2025-04-01T10:00:00"

CH_HOST="localhost"
CH_PORT="8123"
CH_USER="default"
CH_PASSWORD=""
CH_DATABASE="default"

LLM_API_BASE="http://localhost:8000"
LLM_API_KEY="sk-placeholder"
LLM_MODEL="qwen2.5-72b-instruct"

INCIDENT_CONTEXT="Airflow workers failing on ndp-p01. Tasks hanging, ImagePullBackOff on several pods, scheduler restarting."

# ── Директории ─────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Шаг 1: выгрузка логов из ClickHouse ───────────────────────────────────────

echo "=== Step 1: Fetching logs from ClickHouse ==="
python "$SCRIPT_DIR/fetch_logs.py" \
    --start "$PERIOD_START" \
    --end   "$PERIOD_END" \
    --ch-host "$CH_HOST" \
    --ch-port "$CH_PORT" \
    --ch-user "$CH_USER" \
    --ch-password "$CH_PASSWORD" \
    --ch-database "$CH_DATABASE" \
    --queries "0,1" \
    --max-rows 5000 \
    --output "$SCRIPT_DIR/logs.json"

# ── Шаг 2: суммаризация ────────────────────────────────────────────────────────

echo ""
echo "=== Step 2: Summarizing ==="
python -m summarizer.main \
    --input         "$SCRIPT_DIR/logs.json" \
    --format        json \
    --schema-hint   "timestamp: event time ISO8601, end_time: event end time, cnt: number of repeated log lines, namespace: k8s namespace, pod_name: pod name, container_name: container name, log_text: log message (containers query); reason: k8s event reason, object_name: affected object name, message: event message (events query)" \
    --prompt        "Analyze the Kubernetes incident: $INCIDENT_CONTEXT. Period: $PERIOD_START to $PERIOD_END. Find root causes, key error events, and actionable recommendations." \
    --output-schema "$SCRIPT_DIR/schema.json" \
    --map-prompt    "$SCRIPT_DIR/map_prompt.txt" \
    --reduce-prompt "$SCRIPT_DIR/reduce_prompt.txt" \
    --model         "$LLM_MODEL" \
    --api-base      "$LLM_API_BASE" \
    --api-key       "$LLM_API_KEY" \
    --map-concurrency 5 \
    --token-budget  6000 \
    --context-tokens 32000 \
    --output        "$SCRIPT_DIR/result.json"

echo ""
echo "=== Done: $SCRIPT_DIR/result.json ==="
