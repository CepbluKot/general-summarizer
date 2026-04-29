# General Summarizer — Design

**Goal:** Universal MAP-REDUCE summarizer that processes large datasets (JSON array or plain text) and produces a structured JSON result defined by a user-provided JSON Schema.

**Architecture:** Token-based chunking → parallel MAP (LLM per chunk) → tree REDUCE until 1 result remains. Prompts are user-overridable with sensible defaults.

**Tech Stack:** Python 3.12, instructor (Mode.JSON_SCHEMA), openai-compatible API, asyncio, pydantic (config only).

---

## Data Flow

```
File (json | text)
      ↓
loader.py        — читает файл, возвращает list[str]
                   json: каждый объект → json.dumps(obj)
                   text: каждая непустая строка → элемент
      ↓
chunker.py       — нарезает list[str] на chunks по токенному бюджету (chars // 3)
                   возвращает list[list[str]]
      ↓
MAP (async)      — параллельно: каждый chunk → LLM → partial JSON (output_schema)
      ↓
REDUCE (tree)    — группы по token budget → LLM merge → повторяем пока не останется 1
      ↓
result.json      — финальный JSON согласно output_schema
```

---

## File Structure

```
general-summarizer/
  summarizer/
    __init__.py
    main.py             # CLI точка входа (argparse + asyncio)
    config.py           # PipelineConfig dataclass
    loader.py           # чтение файла, парсинг форматов
    chunker.py          # нарезка по токенам
    llm_client.py       # вызов LLM через instructor (Mode.JSON_SCHEMA)
    pipeline.py         # MAP-REDUCE оркестратор
    prompts/
      __init__.py
      map_default.txt      # дефолтный MAP промпт
      reduce_default.txt   # дефолтный REDUCE промпт
      compress_default.txt # дефолтный compress промпт
  docs/
    superpowers/specs/  # этот файл
  README.md             # руководство пользователя
  CLAUDE.md             # контекст для LLM-ассистента по коду
  PROMPT_GUIDE.md       # руководство по написанию промптов
  requirements.txt
```

---

## CLI

```bash
python -m summarizer.main \
  --input       data.json \          # входной файл
  --format      json \               # json | text
  --schema-hint "id: ..., msg: ..." \# описание полей (только для json)
  --prompt      "найди топ-5 проблем" \ # цель пользователя
  --output-schema schema.json \      # JSON Schema выходного формата
  --map-prompt      map.txt \        # (опц.) переопределить MAP промпт
  --reduce-prompt   reduce.txt \     # (опц.) переопределить REDUCE промпт
  --compress-prompt compress.txt \   # (опц.) переопределить compress промпт
  --model       qwen2.5-72b \
  --api-base    http://localhost:8000 \
  --api-key     sk-... \
  --output      result.json \        # (опц.) по умолч. stdout
  --map-concurrency 5 \
  --token-budget    6000             # токенов на чанк
```

---

## Компоненты

### loader.py
- `load(path, format) -> list[str]`
- `json`: читает JSON массив, каждый объект сериализует через `json.dumps`
- `text`: читает построчно, фильтрует пустые строки

### chunker.py
- `chunk(rows, token_budget) -> list[list[str]]`
- Оценка токенов: `len(s) // 3`
- Набирает строки пока не превышен бюджет, затем открывает новый чанк

### llm_client.py
- `call(prompt_text, output_schema, model, api_base, api_key) -> dict`
- Использует `instructor.from_openai(client, mode=instructor.Mode.JSON_SCHEMA)`
- `response_model` — dict с JSON Schema от пользователя
- SSL verification отключён (внутренние деплои)

### pipeline.py
- `run(rows, config) -> dict` (async)
- MAP: `asyncio.gather` с семафором `map_concurrency`
- REDUCE: tree-merge с полной обработкой edge cases:

**Adaptive group size** — размер группы не фиксирован, вычисляется динамически:
```
avg_tokens = среднее по первым 5 элементам очереди
group_size = max(2, int(context_tokens * 0.55 / avg_tokens))
```

**Основной цикл REDUCE** — повторяется пока items > 1:
1. Нарезаем на группы по `group_size`
2. Каждую группу → `_merge_group`
3. После мержа: если результат > `compression_target` → LLM-сжатие
4. Результат в следующий раунд

**`_merge_group` — обработка ошибок:**
- `ContextOverflowError` при группе > 2 → делим пополам, мержим каждую часть рекурсивно, мержим два результата
- `ContextOverflowError` при группе ≤ 2 → сжимаем items по одному, пробуем merge после каждого
- `LLMUnavailableError` (502/503) → ждём 30с, повторяем
- `LLMUnavailableError` (timeout) → удваиваем timeout, сжимаем, повторяем до 5 раз
- Финальный **программный fallback**: массивы — объединяем, скалярные поля — берём из первого item, строки — конкатенируем через `\n---\n`

**Компрессия** — отдельный LLM-вызов с промптом:
```
Сожми этот JSON-саммари вдвое, сохрани самое важное.
Верни тот же JSON Schema.
```
Пользователь может переопределить compress-промпт через `--compress-prompt compress.txt`

### Промпты
Плейсхолдеры заполняются через `str.format_map`:

| Плейсхолдер | Этап | Что подставляется |
|---|---|---|
| `{user_prompt}` | MAP + REDUCE | `--prompt` |
| `{schema_hint}` | MAP | `--schema-hint` (пусто для text) |
| `{output_schema}` | MAP + REDUCE | JSON Schema как строка |
| `{chunk_content}` | MAP | строки чанка, `\n`.join |
| `{partial_results}` | REDUCE | JSON частичных результатов |

### config.py
```python
@dataclass
class PipelineConfig:
    input_path: str
    format: str                    # "json" | "text"
    schema_hint: str               # "" если text
    user_prompt: str
    output_schema: dict            # загруженный JSON Schema
    map_prompt_template: str       # текст шаблона
    reduce_prompt_template: str
    model: str
    api_base: str
    api_key: str
    output_path: str | None
    compress_prompt_template: str
    map_concurrency: int = 5
    token_budget: int = 6000
    context_tokens: int = 32000      # окно контекста модели
    compression_target_pct: int = 30 # сжимаем если результат > 30% контекста
    max_reduce_rounds: int = 20
```

---

## Post-implementation документация

После реализации создаются три markdown-файла:

- **README.md** — руководство пользователя: установка, примеры запуска, описание всех параметров CLI, примеры schema.json
- **CLAUDE.md** — контекст для LLM-ассистента: карта файлов, что где лежит, как устроен pipeline, как добавить новый формат или изменить промпты
- **PROMPT_GUIDE.md** — руководство по написанию промптов: все плейсхолдеры с примерами, дефолтные промпты, советы по написанию output_schema.json для разных задач

---

## Ограничения / Out of scope

- Нет поддержки markdown таблиц (только json и text)
- Нет ClickHouse, нет алертов, нет зон (incident/context)
- Нет Streamlit UI
- Нет адаптации под Dify (первая версия — pure Python CLI)
