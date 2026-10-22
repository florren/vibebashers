# T-059 — Узлы ingest, normalize, identify_client, gather_context

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Подготовка контекста: нормализация текста, идентификация клиента, сбор операций/логов/истории.

## Разделы ТЗ (docs/TZ.md)
§6 шаги 1–2, §9.1

## Контракты
- `events/sim/signal.schema.json`

## Зависимости
- Зависит от: [T-057](T-057-instrumenty-chteniya-konteksta.md)
- Блокирует: [T-060](T-060-uzel-classify-i-prompty-v1.md), [T-173](T-173-matching-klienta-po-kosvennym-dannym-match-clien.md), [T-210](T-210-trehklassnaya-tonalnost-sentiment-prompt-soglaso.md)

## Что сделать
1. normalize: язык, очистка, извлечение сумм/дат/масок карт регулярками (как подсказки, не замена LLM).
2. identify_client: по client_id, иначе по контактам external_contact (точное совпадение телефона/email/ника) → клиент или «неидентифицированный».
3. gather_context: вызовы инструментов чтения, компактная сводка для промпта (≤ 2 500 токенов), список активных сбоев по системам продукта.

## Критерии приёмки
- [ ] Неидентифицированный сигнал проходит без ошибок (контекст пуст).
- [ ] Сводка контекста содержит найденный error_code при наличии сбоя в окне ±2 сим-часа.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_nodes_context.py
```

## Отчёт субагента
Ветка `feat/b04-agent`, `backend/app/agent/nodes.py`: ingest (status processing + NOTIFY signals), normalize (regex-подсказки сумма/карта/промо/операция + LLM normalization, пост-проверки тональности, запись signals.sentiment/lang), identify_client (client_id → профиль; иначе ник в social_handles → card_last4+регион; запись client_id в сигнал), gather_context (продукты/операции/сбои/связанные инциденты/похожие сигналы; hints по неуспешным операциям клиента; активные сбои без операции — только подсказка), check_rules (движок `app/rules/engine.py` по business_rules → rule_evaluations). Промпты: `app/agent/prompts/v1/{system,normalize,classify,decide}.md` с frontmatter (version, model_hints, output_schema); системное сообщение = system.md + промпт узла с контекстом, user = только текст клиента (так MockProvider и реальная модель видят одно и то же). Время: ~1 ч.
