# T-239 — Красные слова и route_to_product_team: data/red_words.yaml, предобработка нормализатора, фасад-инструмент, красная полоса (данные)

| Поле | Значение |
|---|---|
| Эпик | E19 Кабинет менеджера продукта и продуктовый разрез [ЕТЗ] |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 8 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Детерминированная подсветка юридических и регуляторных угроз до LLM (ЕТЗ FR-2.6) и маршрутизация по направлению (FR-3.6), ТЗ 24.3.

## Разделы ТЗ (docs/TZ.md)
§24.3, §9.2, §9.3, §3.7

## Контракты
- `data/red_words.yaml`
- `events/agent/router_tools.schema.json (route_to_product_team)`
- `events/agent/classification.schema.json (red_words)`

## Зависимости
- Зависит от: [T-213](T-213-router-instrumenty-route-to-department-notify-cu.md), [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md), [T-237](T-237-kontrakty-kabineta-csi-i-vsp-migraciya-0005-open.md)
- Блокирует: [T-262](T-262-scenarii-14-kabinet-menedzhera-krasnye-slova-i-o.md)

## Что сделать
1. `data/red_words.yaml`: версия, основы слов и фразы (суд, налоговая, ФНС, иск, исполнительный лист, судебный приказ, ЦБ, мисселинг), исключения («риск», «искать», «исключить» и т. п.); правки списка — только через данные, пометка `rules-change`.
2. Предобработка в `app/ingest/normalizer.py`: границы слов и морфологические основы, результат — `signals.red_words`, флаг `red_word`, `criticality` не ниже `high`; журнал совпадений в `ingest_messages.meta`.
3. Политика (`policies.py`): красное слово + юридический контекст → обязательный HITL по 9.3; чистые функции, unit-тесты на каждую ветку.
4. Инструмент `route_to_product_team(product_line, signal_id)`: фасад над `route_to_department` (`department = owner_team_code`), первым в списке функций, один шаг `wraps=['route_to_department']`, `router_action = route` совпадает с фактическими вызовами (`policy_checks`).
5. Набор ≥ 60 фраз (в т. ч. «риск», «искать», «исковое»), тест отсутствия ложных срабатываний и пропусков; данные для UI (признак красной полосы) отдаются в `v_tickets`/`v_signal_normalized`.

## Критерии приёмки
- [ ] ≥ 60 тест-фраз проходят; «риск» и «искать» не срабатывают.
- [ ] `route_to_product_team` виден в `agent_steps` с `wraps`; запись в БД — только через инструмент.
- [ ] Красные слова не дублируют детектор мисселлинга речи (22.4).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_red_words.py backend/tests/unit/test_router_product_team.py
make scenario ID=cabinet_red_words_report
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
