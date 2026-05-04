# Dify MAP-REDUCE Summarizer Pipeline

Универсальный пайплайн суммаризации произвольных данных через MAP-REDUCE.
Работает со структурированными данными (JSON-массив объектов) и неструктурированным текстом.

---

## Концепция

Входные данные нарезаются на батчи по токенному бюджету. Каждый батч анализируется LLM (MAP). Результаты рекурсивно мержатся попарно (REDUCE) до получения одного итогового результата.

Два режима:
- **json** — входные данные: JSON-массив объектов; выход LLM валидируется по JSON Schema
- **text** — входные данные: произвольный текст; выход LLM — свободный текст

---

## START нода — входные параметры

| Параметр | Тип | Описание |
|---|---|---|
| `raw_input` | String | данные для суммаризации (JSON-строка или plain text) |
| `input_mode` | String | `json` или `text` |
| `map_prompt` | String | системный промпт для LLM MAP |
| `reduce_prompt` | String | системный промпт для LLM REDUCE |
| `output_mode` | String | `json` или `text` |
| `output_schema` | String | JSON Schema строкой (только для `output_mode=json`, иначе пусто) |
| `token_budget` | String | токенов на один батч/группу, например `"6000"` |

---

## MAP Loop

### Loop-переменные

| Переменная | Тип | Начальное значение |
|---|---|---|
| `offset` | Number | `0` |
| `analyses` | Array[Object] | `[]` |

### Condition выхода из loop
```
parse_input.has_more == 0
```

### Ноды внутри MAP Loop (по порядку)

---

#### 1. Code: `parse_input`

Живёт внутри loop. На каждой итерации читает срез `raw_input` начиная с `loop.offset` и возвращает батч. Весь входной массив не материализуется — это обход лимита Dify на 29 элементов в Array.

**json mode:** парсит JSON array, берёт объекты пока не превышен `token_budget` (токены = `len(json(row)) // 3`). Batch — JSON-строка массива.

**text mode:** делит по словам, берёт слова пока не превышен `token_budget` (токены = `len(word) // 3 + 1`). Batch — строка слов через пробел.

```
IN:
  raw_input    ← start.raw_input        (String)
  offset       ← loop.offset            (Number)
  input_mode   ← start.input_mode       (String)
  token_budget ← start.token_budget     (String)

OUT:
  batch        (String) — данные батча
  next_offset  (Number) — новый offset
  has_more     (Number) — 1 если есть ещё данные, 0 если конец
```

---

#### 2. Code: `format_batch`

Формирует User Message для LLM MAP. В json mode добавляет инструкцию по схеме перед данными. В text mode отдаёт строку как есть.

```
IN:
  batch         ← parse_input.batch      (String)
  output_mode   ← start.output_mode      (String)
  output_schema ← start.output_schema    (String)

OUT:
  text (String) — готовый User Message
```

**json mode output:**
```
Output JSON Schema:
{output_schema}

Output ONLY valid JSON matching the schema. No prose, no markdown fences.

Data:
{batch}
```

**text mode output:**
```
Data:
{batch}
```

---

#### 3. LLM MAP

```
System Message: {{start.map_prompt}}
User Message:   {{format_batch.text}}

OUT:
  text (String) — сырой ответ LLM
```

---

#### 4. Code: `parse_output`

Парсит ответ LLM. В json mode делает `json.loads`. В text mode оборачивает в `{"text": "..."}` — чтобы результаты обоих режимов хранились единообразно в `Array[Object]`. Стрипает `<think>...</think>` блоки reasoning-моделей.

```
IN:
  llm_text    ← llm_map.text          (String)
  output_mode ← start.output_mode     (String)

OUT:
  analysis (Object)
```

---

#### 5. Variable Assigner

Обновляем loop-переменные:
```
loop.analyses ← loop.analyses + [parse_output.analysis]   (append)
loop.offset   ← parse_input.next_offset
```

---

## Переход MAP → REDUCE

После выхода из MAP Loop передаём результаты в REDUCE Loop:

```
REDUCE Loop input:
  items      ← map_loop.analyses    (Array[Object])
```

---

## REDUCE Loop

Рекурсивно мержит `items` до одного элемента. Работает проходами: за каждый проход группы мержатся попарно, результаты становятся новым `items`. Повторяется пока `items` не схлопнется в один элемент.

### Loop-переменные

| Переменная | Тип | Начальное значение |
|---|---|---|
| `items` | Array[Object] | `map_loop.analyses` |
| `next_items` | Array[Object] | `[]` |
| `offset` | Number | `0` |

### Condition выхода из loop
```
reduce_update_state.done == 1
```

### Ноды внутри REDUCE Loop (по порядку)

---

#### 1. Code: `reduce_take_group`

Берёт группу элементов из `loop.items` начиная с `loop.offset` по токенному бюджету.

**json mode:** токены = `len(json(item)) // 3`
**text mode:** токены = `len(item["text"]) // 3`

```
IN:
  items        ← loop.items           (Array[Object])
  offset       ← loop.offset          (Number)
  input_mode   ← start.input_mode     (String)
  token_budget ← start.token_budget   (String)

OUT:
  group      (Array[Object]) — группа для мержа
  new_offset (Number)
  has_more   (Number)        — 1 если после группы ещё есть элементы
```

---

#### 2. Code: `format_group`

Формирует User Message для LLM REDUCE.

**json mode:** JSON-массив группы + инструкция по схеме.
**text mode:** текстовые блоки через `---`.

```
IN:
  group         ← reduce_take_group.group    (Array[Object])
  output_mode   ← start.output_mode          (String)
  output_schema ← start.output_schema        (String)

OUT:
  text (String) — готовый User Message
```

**json mode output:**
```
Output JSON Schema:
{output_schema}

Output ONLY valid JSON matching the schema. No prose, no markdown fences.

Partial analyses to merge:
{group as JSON}
```

**text mode output:**
```
{item1.text}

---

{item2.text}

---

{item3.text}
```

---

#### 3. LLM REDUCE

```
System Message: {{start.reduce_prompt}}
User Message:   {{format_group.text}}

OUT:
  text (String) — сырой ответ LLM
```

---

#### 4. Code: `parse_output`

Та же нода что и в MAP. Парсит ответ LLM по `output_mode`.

```
IN:
  llm_text    ← llm_reduce.text       (String)
  output_mode ← start.output_mode     (String)

OUT:
  analysis (Object) — смерженный результат
```

---

#### 5. Code: `reduce_update_state`

Управляет состоянием REDUCE. Добавляет смерженный результат в `next_items`. Когда проход завершён (`has_more == 0`):
- если `next_items` содержит 1 элемент → `done = 1` (финал)
- если больше → `items = next_items`, начинаем новый проход

```
IN:
  items      ← loop.items                     (Array[Object])
  next_items ← loop.next_items                (Array[Object])
  merged     ← parse_output.analysis          (Object)
  new_offset ← reduce_take_group.new_offset   (Number)
  has_more   ← reduce_take_group.has_more     (Number)

OUT:
  items      (Array[Object]) — новый items
  next_items (Array[Object]) — новый next_items
  offset     (Number)        — новый offset
  done       (Number)        — 1 если финальный результат готов
```

---

#### 6. Variable Assigner

```
loop.items      ← reduce_update_state.items
loop.next_items ← reduce_update_state.next_items
loop.offset     ← reduce_update_state.offset
```

---

## END

```
Результат: reduce_loop.items[0]
```

В `json` mode — объект по схеме.
В `text` mode — `{"text": "итоговый текст"}`, берём поле `text`.

---

## Файлы нод

| Файл | Назначение |
|---|---|
| `nodes/parse_input.py` | MAP Loop: парсинг + нарезка батча из raw_input по offset |
| `nodes/format_batch.py` | MAP Loop: формирование User Message для LLM MAP |
| `nodes/parse_output.py` | MAP + REDUCE: парсинг ответа LLM |
| `nodes/append_analysis.py` | (устарел, заменён Variable Assigner append в loop) |
| `nodes/reduce_take_group.py` | REDUCE Loop: нарезка группы из items по offset |
| `nodes/format_group.py` | REDUCE Loop: формирование User Message для LLM REDUCE |
| `nodes/reduce_update_state.py` | REDUCE Loop: обновление состояния прохода |

---

## Тестовые данные (k8s инцидент)

### input_mode
```
json
```

### output_mode
```
json
```

### token_budget
```
3000
```

### raw_input
```json
[
  {"timestamp": "2025-04-01T09:01:00", "namespace": "airflow", "pod_name": "airflow-worker-7f9d4", "container_name": "worker", "log_text": "Error: ImagePullBackOff for image registry.internal/airflow:2.8.1"},
  {"timestamp": "2025-04-01T09:02:10", "namespace": "airflow", "pod_name": "airflow-worker-7f9d4", "container_name": "worker", "log_text": "Failed to pull image: context deadline exceeded"},
  {"timestamp": "2025-04-01T09:03:45", "namespace": "airflow", "pod_name": "airflow-scheduler-6b8c2", "container_name": "scheduler", "log_text": "Task instance PID 4821 heartbeat timed out"},
  {"timestamp": "2025-04-01T09:05:00", "namespace": "airflow", "pod_name": "airflow-worker-3a1f7", "container_name": "worker", "log_text": "OOMKilled: container exceeded memory limit 2Gi"},
  {"timestamp": "2025-04-01T09:07:30", "namespace": "kube-system", "pod_name": "coredns-5d78c9869d-xk2pq", "container_name": "coredns", "log_text": "SERVFAIL reply for registry.internal.: read udp timeout"}
]
```

### map_prompt
```
You are a senior SRE analyzing a Kubernetes log fragment during an incident.

Incident: Airflow workers failing on ndp-p01. Tasks hanging, ImagePullBackOff on several pods.

Analyze the log fragment and extract key events, anomalies, and hypotheses.
Focus on errors, crashes, timeouts, OOM, and scheduling failures.
This is a PARTIAL analysis — only capture what you see in this fragment.
```

### reduce_prompt
```
You are a senior SRE synthesizing partial Kubernetes incident analyses.

Incident: Airflow workers failing on ndp-p01. Tasks hanging, ImagePullBackOff on several pods.

Merge the partial analyses into one unified report.
Deduplicate events, keep top hypotheses by confidence, merge recommendations.
```

### output_schema
```json
{"type":"object","properties":{"summary":{"type":"string"},"events":{"type":"array","items":{"type":"object","properties":{"timestamp":{"type":"string"},"description":{"type":"string"},"severity":{"type":"string","enum":["critical","high","medium","low","info"]}}}},"hypotheses":{"type":"array","items":{"type":"object","properties":{"title":{"type":"string"},"confidence":{"type":"string","enum":["low","medium","high"]}}}},"recommendations":{"type":"array","items":{"type":"string"}}}}
```
