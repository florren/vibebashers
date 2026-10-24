# T-173 — Матчинг клиента по косвенным данным (match_client_by_hints)

| Поле | Значение |
|---|---|
| Эпик | E15 Внешние площадки и автономный возврат [BRD] |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Идентификация автора отзыва по нику, маскированной карте, телефону, городу и продукту с уверенностью и порогом автономии (ТЗ 21.3, BRD FR 1.3).

## Разделы ТЗ (docs/TZ.md)
§6 (шаг 3), §21.3

## Контракты
- `events/agent/client_match.schema.json`
- `events/agent/normalization.schema.json`
- `events/agent/tool_call.schema.json`

## Зависимости
- Зависит от: [T-171](T-171-mock-abs-scheta-tarify-provodki-sid-i-invariant.md), [T-057](T-057-instrumenty-chteniya-konteksta.md), [T-059](T-059-uzly-ingest-normalize-identify-client-gather-con.md)
- Блокирует: [T-174](T-174-bystryj-put-agenta-uslovnoe-rebro-act-instant-st.md)

## Что сделать
1. Инструмент match_client_by_hints(contacts_hint) → кандидаты: ник (0,9), card_last4 (0,5 / число совпадений), masked_phone (0,6), город и продукт (+0,1 как уточнение); вероятностная комбинация; порог identified ≥ 0,8.
2. Узел identify_client: при external_contact/contacts_hint вызывает инструмент; decision identified|ambiguous|not_found; ambiguous → уточняющий вопрос в личный канал или HITL, never → автоматический возврат.
3. Панель Log: строка «Mock CRM: N кандидатов, лучший 0,93 (ник + карта)».
4. Тесты на наборе reviews_v1 (T-178): точность ≥ 90 % при наличии ника или ник+карта; на коллизиях last4 — ambiguous.

## Критерии приёмки
- [ ] Точность матчинга на reviews_v1 ≥ 90 %, ложных identified — 0.
- [ ] Инструмент логируется в agent_steps.tool_calls с результатом по схеме client_match.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_match_client.py -k reviews_v1
```

## Отчёт субагента
Ветка `work-florren`. `app/agent/matching.py`: ник 0,9, last4 = 0,5 / число совпадений, телефон 0,6, город и продукт +0,1; вероятностная комбинация; `identified` только при одном кандидате ≥ 0,8. Инструмент `match_client_by_hints` пишет `client_match` в `agent_steps.tool_calls`, узел `identify_client` вызывает его и ставит в reasoning строку «Mock CRM: …». Ambiguous не проставляет `client_id` и оставляет уверенность 0, поэтому автономный возврат не проходит. Отклонение: отдельного файла `reviews_v1` нет (так закрыт T-178) — 100 кейсов собраны в `tests/unit/test_match_client.py`. Контракты не менялись.
