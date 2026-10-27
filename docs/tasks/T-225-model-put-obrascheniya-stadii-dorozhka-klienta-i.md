# T-225 — Модель «Путь обращения»: стадии, дорожка клиента, итог; GET /api/journey/{ref} и /api/journey/latest, заметки ведущего

| Поле | Значение |
|---|---|
| Эпик | E22 Сквозная демонстрация «Путь обращения» [АРХ] |
| Субагент | `SA-Trace` (модель следа, поиск, путь обращения [АРХ]) |
| Оценка | M (1–2 дня) |
| Волна | 8 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Повествовательная проекция следа (ТЗ 27.2–27.5): восемь стадий, события стадий, дорожка «глазами клиента», итог — для экрана показа.

## Разделы ТЗ (docs/TZ.md)
§27.2, §27.3, §27.5, §6

## Контракты
- `events/trace/journey.schema.json`
- `api/openapi.yaml: GET /api/journey/{ref}, GET /api/journey/latest`

## Зависимости
- Зависит от: [T-224](T-224-sborschik-sleda-app-trace-kauzalnyj-obhod-fazy-d.md), [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md), [T-174](T-174-bystryj-put-agenta-uslovnoe-rebro-act-instant-st.md)
- Блокирует: [T-226](T-226-ekran-put-obrascheniya-journey-ref-stepper-iz-8.md)

## Что сделать
1. `backend/app/trace/journey.py`: отображение `trace_event_kind` → стадия 1–8 (таблица ТЗ 27.2), статус стадии `done|active|pending|skipped|waiting_human`, длительности (сим и реальные), «время до первого ответа клиенту».
2. Дорожка клиента: только то, что клиент видел — `notifications` (статус доставки), `external_replies`, письма Mailpit/Telegram, `client_reactions`; сообщение имеет вид `ack|public_reply|status|final|gift|clarification`; пустая дорожка с причиной («ждём решения человека»).
3. Итог (`summary`): класс исхода, деньги (возврат, предотвращённая потеря), бейдж режима; `GET /api/journey/latest?origin=jury|feed|sim|any` для режима «Следить».
4. Заметки ведущего: `backend/app/trace/notes/journey_notes.yaml` — тезисы по стадиям и сценариям (1, 8, 9, 11), отдаются в ответе при `presenter=1`.
5. Тесты: три траектории сценария 12 (автономная, HITL, эскалация) — все применимые стадии, дорожка клиента совпадает с таблицами; p95 ≤ 300 мс.

## Критерии приёмки
- [ ] Для сигналов сценариев 1, 8, 11 стадии и дорожка клиента соответствуют ТЗ 27.2–27.3.
- [ ] `/api/journey/latest` возвращает последний путь нужного происхождения; ответ валиден по схеме.
- [ ] Нет записи в БД и вызовов LLM.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_journey.py
curl -s localhost:8000/api/journey/latest?origin=jury | jq '.stages[].status'
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
