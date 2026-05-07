# General Summarizer — Airflow + Kubernetes

Запуск MAP-REDUCE суммаризатора через Airflow + KubernetesPodOperator.

---

## Структура

```
airflow/
  Dockerfile          — образ суммаризатора
  dags/
    summarizer_dag.py — Airflow DAG (KubernetesPodOperator)
  k8s/
    pvc.yaml          — PersistentVolumeClaims для данных и артефактов
  README.md
```

---

## 1. Сборка и публикация образа

```bash
# Из корня репозитория
docker build -f airflow/Dockerfile -t registry.your-company.com/general-summarizer:latest .
docker push registry.your-company.com/general-summarizer:latest
```

Замени `registry.your-company.com` на свой registry. Обнови `IMAGE` в `dags/summarizer_dag.py`.

---

## 2. Создание PVC в k8s

```bash
kubectl apply -f airflow/k8s/pvc.yaml
```

Два PVC в namespace `airflow`:
- `summarizer-data` — входные файлы, схемы, результаты (монтируется в `/data`)
- `summarizer-runs` — артефакты pipeline: map/, reduce/, llm/ (монтируется в `/app/runs`)

Требуют `ReadWriteMany` — нужен StorageClass с поддержкой RWX (NFS, CephFS и т.п.).
Поправь `storageClassName` в `pvc.yaml` под свой кластер.

---

## 3. Положить файлы в PVC

Входные файлы (`input.json`, `schema.json`) нужно предварительно загрузить в PVC.
Варианты:

```bash
# через временный pod
kubectl run loader --image=busybox --restart=Never \
  --overrides='{"spec":{"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"summarizer-data"}}],"containers":[{"name":"loader","image":"busybox","command":["sleep","3600"],"volumeMounts":[{"name":"data","mountPath":"/data"}]}]}}' \
  -n airflow

kubectl cp input.json airflow/loader:/data/input.json
kubectl cp schema.json airflow/loader:/data/schema.json
kubectl delete pod loader -n airflow
```

---

## 4. Airflow Variables

В Airflow UI → Admin → Variables:

| Key | Value |
|---|---|
| `LLM_API_BASE` | `http://llm-server.your-cluster:8000` |
| `LLM_API_KEY` | `sk-your-key` |
| `LLM_MODEL` | `qwen2.5-72b-instruct` |

---

## 5. Установка провайдера Kubernetes для Airflow

```bash
pip install apache-airflow-providers-cncf-kubernetes
```

---

## 6. Запуск DAG

Через UI (Trigger DAG w/ config):

```json
{
  "input_path":         "/data/input.json",
  "input_format":       "json",
  "output_mode":        "json",
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
airflow dags trigger general_summarizer --conf '{...}'
```

---

## 7. Параметры DAG

| Параметр | Тип | Описание |
|---|---|---|
| `input_path` | String | путь к файлу данных в поде (`/data/...`) |
| `input_format` | json/text | формат входных данных |
| `output_mode` | json/text | json: схема + валидация; text: свободный формат |
| `prompt` | String | задача суммаризации |
| `output_schema_path` | String | путь к JSON Schema (только для `output_mode=json`) |
| `output_path` | String | путь для записи результата |
| `schema_hint` | String | описание полей (опционально) |
| `map_concurrency` | int | параллельность MAP (default 3) |
| `token_budget` | int | токенов на батч (default 6000) |
| `context_tokens` | int | контекст модели в токенах (default 32000) |

---

## 8. Конфигурация DAG

В `dags/summarizer_dag.py` поправь под свой кластер:

```python
IMAGE          = "registry.your-company.com/general-summarizer:latest"
K8S_NAMESPACE  = "airflow"
K8S_DATA_PVC   = "summarizer-data"
K8S_RUNS_PVC   = "summarizer-runs"
```