# T-208 — Приём транскриптов: JSON/TXT парсеры, POST /api/ingest/transcripts (JSON и multipart), импорт каталога, таблица transcripts

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Готовый транскрипт диалога файлом или по REST сохраняется в transcripts и запускает анализы client_signal / employee_quality (ДТЗ FR-1.1, FR-4.1; ТЗ 3.7).

## Разделы ТЗ (docs/TZ.md)
§3.7, §13, §16.4, §22.8

## Контракты
- `events/ingest/transcript.schema.json`
- `events/ingest/ingest_event.schema.json`
- `db/schema.sql: transcripts, signals.transcript_id`
- `api/openapi.yaml: /api/ingest/transcripts*, TranscriptBrief, TranscriptDetail`

## Зависимости
- Зависит от: [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md)
- Блокирует: [T-216](T-216-paketnyj-analiz-transkripta-pacing-batch-transcr.md)

## Что сделать
1. Парсер TXT: строки «[чч:мм:сс] Роль: реплика» / «Роль: реплика», словарь синонимов ролей (Сотрудник/Оператор/Менеджер → employee; Клиент/Абонент → client), многострочные реплики; результат — объект по схеме transcript.
2. POST /api/ingest/transcripts: JSON-тело или multipart с несколькими файлами; определение kind/branch/employee из метаданных или query; запись transcripts (status=received); фоновая задача analyze(transcript_id, analyses).
3. Анализ client_signal: реплики клиента → текст обращения → normalizer (origin=transcript, канал branch/call/chat по kind) → обычный граф; сохранить signal_id. Анализ employee_quality: создать audio_sessions (source=transcript, pacing=batch) и передать в T-216.
4. POST /api/ingest/transcripts/import — обход data/import/transcripts/ (JSON+TXT), идемпотентность по имени файла+хэшу; GET список/деталь; события ingest.transcript_received/analyzed.
5. Тесты: 4 TXT-варианта, 2 JSON, ошибка формата → 422, сигнал появляется ≤ 3 с.

## Критерии приёмки
- [ ] scenario10_retail.txt и его JSON-двойник дают одинаковый объект turns.
- [ ] После приёма транскрипта ≤ 3 с есть сигнал с origin=transcript и ссылка transcripts.signal_id.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_transcript_parser.py backend/tests/integration/test_ingest_transcripts.py
```

## Отчёт субагента
- Реализовано в `feat/B07-compliance`: `backend/app/compliance/txt_parser.py` (TXT «[чч:мм:сс] Роль: …», метаданные `# key: value; …`, многострочные реплики, алиасы ролей), `transcripts.py::create_transcript/load_file` (валидация по `ingest/transcript`, резолв отделения/сотрудника, событие `ingest.transcript_received`). API: `GET/POST /api/ingest/transcripts` (JSON или multipart JSON/TXT), `POST …/import` (data/import/transcripts, дедуп по имени файла), `GET …/{id}` (реплики с находками), `POST …/{id}/analyze`. Тесты `tests/compliance/test_pure.py`.

Дополнение по ревизии 01.11.2026, ветка `codex/cli-workflow-completion`: `make import-transcripts CX_BASE_URL=…` теперь вызывает серверный импорт через существующий API вместо успешной заглушки. CLI выводит accepted/duplicates/rejected; код 1 при rejected, 2 при HTTP/некорректном ответе. Успешный приём отделён от завершения фонового анализа. Регрессии с MockTransport проверяют путь, повторный импорт, частичный отказ и некорректный ответ. Контракты и API не менялись.

PR ревизии: https://github.com/florren/vibebashers/pull/150; общий журнал проверок — дополнение T-141 и описание PR.
