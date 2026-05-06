# General Summarizer — Airflow

Запуск MAP-REDUCE суммаризатора через Airflow + DockerOperator.

---

## Структура

```
airflow/
  Dockerfile          — образ суммаризатора
  dags/
    summarizer_dag.py — Airflow DAG
  README.md
```

---

## 1. Сборка Docker-образа

Из корня репозитория:

```bash
docker build -f airflow/Dockerfile -t general-summarizer:latest .
```

Образ включает пакет `summarizer/` и все зависимости из `requirements.txt`.

---

## 2. Установка провайдера Docker для Airflow

```bash
pip install apache-airflow-providers-docker
```

---

## 3. Подготовка директорий

```bash
mkdir -p /opt/airflow/data   # входные файлы, схемы, результаты
mkdir -p /opt/airflow/runs   # артефакты pipeline (map/, reduce/, llm/)
```

Положи в `/opt/airflow/data/`:
- `input.json` — входные данные (JSON-массив объектов или plain text)
- `schema.json` — JSON Schema для вывода

Пример `schema.json`:
```json
{
  "type": "object",
  "properties": {
    "summary": {"type": "string"},
    "events": {"type": "array", "items": {"type": "object"}},
    "recommendations": {"type": "array", "items": {"type": "string"}}
  }
}
```

---

## 4. Airflow Variables

В Airflow UI → Admin → Variables добавь:

| Key | Value |
|---|---|
| `LLM_API_BASE` | `http://your-llm-server:8000` |
| `LLM_API_KEY` | `sk-your-key` |
| `LLM_MODEL` | `qwen2.5-72b-instruct` |

---

## 5. DAG — параметры запуска

DAG `general_summarizer` запускается вручную (schedule=None).

При триггере через UI (Trigger DAG w/ config) передай JSON:

```json
{
  "input_path":         "/data/input.json",
  "input_format":       "json",
  "prompt":             "Incident: Airflow workers failing. Find root causes.",
  "output_schema_path": "/data/schema.json",
  "output_path":        "/data/output.json",
  "schema_hint":        "timestamp: ISO8601, pod_name: k8s pod, log_text: log message",
  "map_concurrency":    3,
  "token_budget":       6000,
  "context_tokens":     32000
}
```

Или через CLI:

```bash
airflow dags trigger general_summarizer --conf '{
  "input_path": "/data/input.json",
  "input_format": "json",
  "prompt": "Summarize k8s incident logs",
  "output_schema_path": "/data/schema.json",
  "output_path": "/data/output.json"
}'
```

---

## 6. Volumes

| Host | Container | Назначение |
|---|---|---|
| `/opt/airflow/data` | `/data` | входные файлы и результаты |
| `/opt/airflow/runs` | `/app/runs` | артефакты: map/, reduce/, llm/ |

После выполнения результат в `/opt/airflow/data/output.json`.
Артефакты в `/opt/airflow/runs/{timestamp}/`.

---

## 7. Запуск Airflow с доступом к Docker

Airflow worker должен иметь доступ к Docker socket:

```yaml
# docker-compose.yml (фрагмент)
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
  - /opt/airflow/data:/opt/airflow/data
  - /opt/airflow/runs:/opt/airflow/runs
```

---

## 8. Проверка образа без Airflow

```bash
docker run --rm \
  -v /opt/airflow/data:/data \
  -v /opt/airflow/runs:/app/runs \
  -e LLM_API_BASE=http://your-llm:8000 \
  -e LLM_API_KEY=sk-key \
  -e LLM_MODEL=qwen2.5-72b-instruct \
  general-summarizer:latest \
  --input /data/input.json \
  --format json \
  --prompt "Summarize the logs" \
  --output-schema /data/schema.json \
  --output /data/output.json
```
