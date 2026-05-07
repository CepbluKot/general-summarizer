"""
Airflow DAG: General Summarizer

Запускает MAP-REDUCE суммаризатор как Pod в Kubernetes через KubernetesPodOperator.

Входные/выходные файлы передаются через PVC, примонтированный в /data.
Артефакты runs/ пишутся в отдельный PVC.

Airflow Variables (Admin → Variables):
  LLM_API_BASE  — например http://llm-server:8000
  LLM_API_KEY   — API ключ
  LLM_MODEL     — название модели

Params (при триггере):
  input_path         — путь к входному файлу внутри пода (/data/...)
  input_format       — json | text
  output_mode        — json | text
  prompt             — задача суммаризации
  output_schema_path — путь к JSON Schema (только для output_mode=json)
  output_path        — путь для результата (/data/...)
  schema_hint        — описание полей (опционально)
  map_concurrency    — параллельность MAP
  token_budget       — токенов на батч
  context_tokens     — размер контекста модели
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.models import Param, Variable
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from kubernetes.client import models as k8s

# ── CONFIG ────────────────────────────────────────────────────────────────────

IMAGE          = Variable.get("SUMMARIZER_IMAGE",     default_var="registry.your-company.com/general-summarizer:latest")
K8S_NAMESPACE  = Variable.get("SUMMARIZER_NAMESPACE", default_var="airflow")
K8S_DATA_PVC   = Variable.get("SUMMARIZER_DATA_PVC",  default_var="summarizer-data")
K8S_RUNS_PVC   = Variable.get("SUMMARIZER_RUNS_PVC",  default_var="summarizer-runs")

# ── DAG ───────────────────────────────────────────────────────────────────────

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
    tags=["summarizer", "llm", "k8s"],
    params={
        "input_path":         Param("/data/input.json",  type="string"),
        "input_format":       Param("json",              type="string", enum=["json", "text"]),
        "output_mode":        Param("json",              type="string", enum=["json", "text"]),
        "prompt":             Param("Summarize the data", type="string"),
        "output_schema_path": Param("/data/schema.json", type="string"),
        "output_path":        Param("/data/output.json", type="string"),
        "schema_hint":        Param("",                  type="string"),
        "map_concurrency":    Param(3,                   type="integer", minimum=1, maximum=20),
        "token_budget":       Param(6000,                type="integer", minimum=1000),
        "context_tokens":     Param(32000,               type="integer", minimum=4000),
    },
) as dag:

    run_summarizer = KubernetesPodOperator(
        task_id="run_summarizer",
        name="general-summarizer",
        namespace=K8S_NAMESPACE,
        image=IMAGE,
        image_pull_policy="Always",

        arguments=[
            "--input",            "{{ params.input_path }}",
            "--format",           "{{ params.input_format }}",
            "--output-mode",      "{{ params.output_mode }}",
            "--prompt",           "{{ params.prompt }}",
            "--output",           "{{ params.output_path }}",
            "--schema-hint",      "{{ params.schema_hint }}",
            "--map-concurrency",  "{{ params.map_concurrency | string }}",
            "--token-budget",     "{{ params.token_budget | string }}",
            "--context-tokens",   "{{ params.context_tokens | string }}",
            # --output-schema только в json режиме
            "{% if params.output_mode == 'json' %}--output-schema{% endif %}",
            "{% if params.output_mode == 'json' %}{{ params.output_schema_path }}{% endif %}",
        ],

        env_vars=[
            k8s.V1EnvVar(name="LLM_API_BASE", value="{{ var.value.LLM_API_BASE }}"),
            k8s.V1EnvVar(name="LLM_API_KEY",  value="{{ var.value.LLM_API_KEY }}"),
            k8s.V1EnvVar(name="LLM_MODEL",    value="{{ var.value.LLM_MODEL }}"),
        ],

        volumes=[
            k8s.V1Volume(
                name="data",
                persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(claim_name=K8S_DATA_PVC),
            ),
            k8s.V1Volume(
                name="runs",
                persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(claim_name=K8S_RUNS_PVC),
            ),
        ],

        volume_mounts=[
            k8s.V1VolumeMount(name="data", mount_path="/data"),
            k8s.V1VolumeMount(name="runs", mount_path="/app/runs"),
        ],

        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "500m", "memory": "512Mi"},
            limits={"cpu": "2",     "memory": "2Gi"},
        ),

        get_logs=True,
        is_delete_operator_pod=True,
        in_cluster=True,
    )
