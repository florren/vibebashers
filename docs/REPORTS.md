# Логирование и отчёт о качестве

Цель — чтобы человек и ИИ-агент по одному документу понимали: **что сломалось**, **что работает, но не так**, и **что доработать** — с указанием, куда смотреть. Три слоя: журнал событий (JSONL), метрики HTTP в процессе и агрегированный отчёт из БД.

## 1. Где что лежит

| Слой | Что | Где | Кому |
|---|---|---|---|
| Журнал | каждая запись structlog уровня `info+` как строка JSON (`timestamp`, `level`, `event`, поля; у HTTP-запросов `request_id`) | `backend/var/log/app.jsonl` (ротация 20 МБ × 3; `LOG_DIR`, `LOG_JSONL`, `LOG_JSONL_LEVEL` в `.env`), `GET /api/reports/log?level=warning&event=…` | разбор конкретного сбоя |
| HTTP | счётчики по маршрутам (всего, 2xx/4xx/5xx/501/422, avg/max мс, медленные > 2 с), кольцевой буфер последних 500 ошибок | `GET /api/reports/http` (с момента запуска процесса) | «API падает / тормозит / вызывают нереализованное» |
| Отчёт | агрегаты по БД + HTTP + правила рекомендаций + индекс здоровья | `GET /api/reports/quality?run_id=all|current|N&format=json|md`, `make report` → `data/reports/quality-<ts>.md/.json`, `latest.md`; вкладка **«Качество»** на `/engine` | еженедельный разбор, постановка задач агентам |

Журнал и отчёты не коммитятся (`.gitignore`). Таблицы БД не добавлялись: источники — уже существующие `agent_runs`, `agent_steps`, `human_decisions`, `incidents`, `signals`, `followups`, `scenarios.last_result`, `compliance_alerts`, `transcripts`.

## 2. Как читать отчёт

**Сводка** — одна таблица и индекс здоровья 0–100 (штрафы: ошибки прогонов/шагов, доля fallback, доля правок HITL, SLA, проваленные сценарии, 5xx, транскрипты с ошибкой). Индекс — ориентир для сравнения «до/после», не KPI.

**Что доработать** — список рекомендаций `severity` (🔴 high / 🟡 medium / 🟢 low), `area` и строка «где смотреть» (эндпоинт, таблица/поле, файл, промпт). Правила — в `backend/app/observability/quality.py::_recommend`:

| Сигнал | Трактовка | Правило |
|---|---|---|
| `agent_runs.outcome='failed'`, `agent_steps.status in (error, retry)` | **сломалось** | любой failed → high; узел с ≥ 5 % ошибок при ≥ 5 шагах → high с примером ошибки |
| `agent_steps.status='fallback'` | модель не отвечала — решение приняли правила/mock | ≥ 50 % LLM-шагов → medium («на демо это заглушки»); 5–50 % → low |
| `human_decisions.decision in (modify, reject)` | **работает, но не так**: агент предложил, человек поправил | ≥ 30 % от решённых при ≥ 3 → high (с полями, которые меняют чаще); иначе medium |
| HITL без решения ≥ 20 | очередь копится | medium |
| `incidents.sla_breached` ≥ 20 % | маршрутизация/эскалации | high |
| `scenarios.last_result.passed=false` | регресс сценария ТЗ | high с кодами проваленных проверок; не запускавшиеся → low |
| `compliance_alerts.decision='false_positive'` ≥ 25 % | детектор шумит | medium (ослабить ключевые фразы / поднять порог) |
| `transcripts.status='failed'` | парсер/анализ упал | high с текстом ошибки |
| HTTP 5xx | сломалось | high с худшим маршрутом |
| HTTP 501 | **спрос на нереализованное** — вызвали функцию-заглушку | medium: это очередь доработок по спросу |
| медленные запросы | производительность | low |

Дальше разделы с деталями: **Агент по узлам** (шаги, ok/fallback/error, p50/p95, токены), **HITL** (каждая правка: причина, изменённые поля, комментарий, кто), **Сценарии**, **Инциденты с нарушением SLA**, **Транскрипты с ошибкой**, **HTTP**.

## 3. Как пользуется агент (Codex / Cursor / Computer)

1. Перед починкой: `make report` (или `curl -s localhost:8000/api/reports/quality?format=md`) — берёт верхние 🔴, читает «где смотреть».
2. Детали: `GET /api/engine/runs/{id}` для прогона, `GET /api/reports/log?event=http_request&level=error` или `jq` по `app.jsonl` с `request_id`; для сценариев — `make scenario ID=…`.
3. После правки: повторный `make report` — индекс здоровья и список рекомендаций должны измениться; разницу (`data/reports/quality-*.json`) приложить к PR в «Отчёт субагента».

Полезные команды:

```bash
make report                                        # все запуски, напрямую из БД
make report RUN=12                                 # один запуск эмуляции
CX_BASE_URL=http://localhost:8000 make report      # через API: добавятся HTTP-метрики процесса
tail -f backend/var/log/app.jsonl | jq -c 'select(.level!="debug")'
jq -c 'select(.request_id=="f8d51379ca1f")' backend/var/log/app.jsonl
```

## 4. Как пользуется человек

- На показе: вкладка «Качество» на `/engine` — индекс здоровья, рекомендации, узлы агента. После демо — `make report`, файл в `data/reports/` можно отправить команде.
- Еженедельно: сравнить `latest.md` с прошлым; каждую 🔴 превратить в карточку `docs/tasks` или задачу агенту со ссылкой «где смотреть».
- Разбор HITL: раздел «HITL» показывает, что именно люди меняют у агента — это материал для few-shot (`human_decisions.use_as_fewshot`) и правок промптов `backend/app/agent/prompts/`.

## 5. Как добавить новую проверку

1. Запрос только на чтение в `build_quality_report` (таблицы из `contracts/db/schema.sql`), поле в `summary`.
2. Правило в `_recommend` (порог, `severity`, `area`, текст и «где смотреть») и при необходимости штраф в `_health`.
3. Строка в `render_markdown`; при новых полях `summary` — обновить `QualityReport` в `contracts/api/openapi.yaml` (contract-change) и перегенерировать TS-типы.
4. Тест в `backend/tests/unit/test_quality_report.py`.

## 6. Что логируется

- `http_request` — метод, маршрут (шаблон), путь, статус, `latency_ms`, `request_id`; `error` при исключении (уровень error для 5xx, warning для 4xx/501/медленных, debug для остальных).
- События агента и симулятора (`agent_*`, `sim_*`, `llm_*`, `compliance_*`, `notify_*`) — как и раньше, из structlog модулей; все попадают в JSONL.
- `unhandled` — необработанное исключение с трассировкой (`app/errors.py`).
