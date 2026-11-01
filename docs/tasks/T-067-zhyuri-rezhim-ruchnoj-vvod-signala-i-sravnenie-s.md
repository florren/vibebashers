# T-067 — Жюри-режим: ручной ввод сигнала и сравнение с правилами

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
Жюри вводит текст — агент обрабатывает на глазах; параллельно mock показывает, что сделали бы правила.

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 2 (жюри-режим), §12.5, §18 сц. 3

## Контракты
- `api/openapi.yaml: POST /api/signals, POST /api/agent/compare`

## Зависимости
- Зависит от: [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md), [T-065](T-065-trassirovka-zapuskov-i-striming-tokenov.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md)
- Блокирует: [T-109](T-109-panel-ii-protiv-pravil.md), [T-206](T-206-nadiktovat-zhalobu-voiceinput-v-rezhime-pokaza-i.md)

## Что сделать
1. POST /api/signals: создание сигнала origin=jury, выбор клиента или неизвестный; при compare_with_mock — второй запуск kind=compare на mock без побочных эффектов (dry-run инструментов записи).
2. POST /api/agent/compare: синхронное сравнение классификаций с diff.
3. Защита: лимит 10 ручных сигналов/мин, длина ≤ 4 000.

## Критерии приёмки
- [ ] Сценарий 3: от ввода до карточки инцидента ≤ 60 с на Ultra; панель показывает различия с mock.
- [x] Compare-запуск не создаёт инцидентов и уведомлений.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=jury_input
```

## Отчёт субагента
Ветка `codex/T-067-jury-compare`, база `f594c43`. Backend реализован: отдельный mock-run на снимке READ ONLY, пропуск act и запрет инструментов записи, отдельные trace-записи, синхронное сравнение с двумя реальными IDs/diff, общий лимит 10/min, длина 3–4000. Основной проход не меняет политику денег/HITL. Диагностические запуски исключены из operational KPI; ошибка и отмена фиксируются в audit.

Контракт `contract-change` 1.5.12 подготовлен отдельным коммитом `31bdac3`; совместимость и обязательное ревью до merge — `docs/reviews/T-067-contract-change.md`. TS types сгенерированы. UI сравнения относится к T-109 и здесь не менялся. Проверка настоящего Ultra и приёмка ≤60 с/панели пока не выполнены: карточка остаётся `in_progress`.

Проверено: `make lint` с документированным `NODE_OPTIONS=--no-experimental-webstorage` (Node26) — успешно, frontend 144 tests; полный unit suite 744 passed/18 skipped; целевые unit после последней доработки 41 passed; 4 integration tests на отдельной PostgreSQL16 scratch БД с mock — успешно. Проверены READ ONLY, неизменность 20 доменных таблиц, неизменяемый снимок до primary, параллельность и отключение compare, persisted standalone IDs. Полный прогон интеграций/сценариев выполняется отдельно; окончательные результаты — в отчёте PR. Реальные внешние LLM не вызывались.
