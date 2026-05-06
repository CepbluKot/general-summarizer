"""
Airflow DAG: General Summarizer

Запускает MAP-REDUCE суммаризатор в Docker-контейнере.

Входные файлы (input, schema) и выходной файл (output) читаются/пишутся
через примонтированный volume /data.

Airflow Variables (задать в Admin → Variables):
  LLM_API_BASE  — например http://llm-server:8000
  LLM_API_KEY   — API ключ
  LLM_MODEL     — название модели

Params (задаются при ручном триггере или в dag_run.conf):
  input_path        — путь к файлу данных внутри контейнера (/data/...)
  input_format      — json | text
  prompt            — задача суммаризации
  output_schema_path — путь к JSON Schema файлу внутри контейнера (/data/...)
  output_path       — путь для результата внутри контейнера (/data/...)
  schema_hint       — описание полей (опционально, только для json)
  map_concurrency   — параллельность MAP (default 3)
  token_budget      — токенов на батч (default 6000)
  context_tokens    — размер контекста модели (default 32000)
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.models import Param, Variable
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount

DATA_DIR = "/opt/airflow/data"   # host-путь, монтируется в /data внутри контейнера
RUNS_DIR = "/opt/airflow/runs"   # host-путь для артефактов runs/

default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="general_summarizer",
    default_args=default_args,
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["summarizer", "llm"],
    params={
        "input_path":         Param("/data/input.json",  type="string", description="Путь к входному файлу внутри контейнера"),
        "input_format":       Param("json",              type="string", enum=["json", "text"]),
        "prompt":             Param("Summarize the data", type="string", description="Задача суммаризации"),
        "output_schema_path": Param("/data/schema.json", type="string", description="Путь к JSON Schema файлу"),
        "output_path":        Param("/data/output.json", type="string", description="Путь для записи результата"),
        "schema_hint":        Param("",                  type="string", description="Описание полей (опционально)"),
        "map_concurrency":    Param(3,                   type="integer", minimum=1, maximum=20),
        "token_budget":       Param(6000,                type="integer", minimum=1000),
        "context_tokens":     Param(32000,               type="integer", minimum=4000),
    },
) as dag:

    run_summarizer = DockerOperator(
        task_id="run_summarizer",
        image="general-summarizer:latest",
        command=[
            "--input",           "{{ params.input_path }}",
            "--format",          "{{ params.input_format }}",
            "--prompt",          "{{ params.prompt }}",
            "--output-schema",   "{{ params.output_schema_path }}",
            "--output",          "{{ params.output_path }}",
            "--schema-hint",     "{{ params.schema_hint }}",
            "--map-concurrency", "{{ params.map_concurrency }}",
            "--token-budget",    "{{ params.token_budget }}",
            "--context-tokens",  "{{ params.context_tokens }}",
        ],
        environment={
            "LLM_API_BASE": "{{ var.value.LLM_API_BASE }}",
            "LLM_API_KEY":  "{{ var.value.LLM_API_KEY }}",
            "LLM_MODEL":    "{{ var.value.LLM_MODEL }}",
        },
        mounts=[
            Mount(source=DATA_DIR, target="/data",      type="bind"),
            Mount(source=RUNS_DIR, target="/app/runs",  type="bind"),
        ],
        docker_url="unix://var/run/docker.sock",
        network_mode="bridge",
        auto_remove="success",
        mount_tmp_dir=False,
    )
