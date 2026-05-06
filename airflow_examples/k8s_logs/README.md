# k8s Logs — Airflow Example

Скрипт забирает k8s логи из ClickHouse и запускает суммаризацию через Airflow DAG.

## Настройка

Открой `trigger.py` и задай параметры в секции `CONFIG`:

| Параметр | Описание |
|---|---|
| `PERIOD_START` / `PERIOD_END` | временной диапазон логов |
| `INCIDENT` | описание инцидента |
| `CH_HOST`, `CH_PORT`, `CH_USER`, `CH_PASSWORD`, `CH_DATABASE` | ClickHouse |
| `AIRFLOW_BASE_URL` | URL Airflow (default `http://localhost:8080`) |
| `AIRFLOW_USER` / `AIRFLOW_PASSWORD` | креды Airflow |
| `DATA_DIR` | host-путь, примонтированный в контейнер как `/data` |

## Запуск

```bash
python airflow_examples/k8s_logs/trigger.py
```

Скрипт:
1. Забирает container logs + k8s events из ClickHouse
2. Сохраняет `k8s_input.json` и `k8s_schema.json` в `DATA_DIR`
3. Триггерит DAG `general_summarizer` через Airflow REST API
4. Ждёт завершения (поллинг каждые 15 сек)
5. Печатает итоговый JSON в stdout

## Зависимости

Только стандартная библиотека Python — никаких дополнительных пакетов.
