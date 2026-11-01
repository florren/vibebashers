# T-091 — Клиент 360

| Поле | Значение |
|---|---|
| Эпик | E7 Рабочее место CX |
| Субагент | `SA-UI-Workspace` (рабочее место CX) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Профиль клиента: сегмент, стиль коммуникации (психотип), продукты, операции, сигналы, инциденты, состояние и история, подарки.

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 3 (Клиент 360), §4.5, §6 шаг 5

## Контракты
- `api/openapi.yaml: clients/{id}/360`

## Зависимости
- Зависит от: [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md), [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md)
- Блокирует: [T-090](T-090-kartochka-incidenta.md)

## Что сделать
1. Drawer/страница с секциями; операции за 72 ч с подсветкой failed и ссылкой на сбой; индикатор churn_risk и текущего состояния с care_score; история состояний как таймлайн.
2. Подсказка стиля коммуникации на основе психотипа (communication_hint_ru) — без термина «психотип» в интерфейсе для клиента.

## Критерии приёмки
- [x] Открывается из сигнала, инцидента и HITL за ≤ 300 мс (кэш).
- [x] Для ушедшего клиента показан инцидент account_closure.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/client360.spec.ts
```

## Отчёт субагента

Ветка `codex/T-091-client360` от `f594c43`. Контрактный коммит `9e7fc15` отдельно добавляет существующий `RunId` к GET `/api/clients/{id}/360` и обновляет generated TS. OpenAPI 1.5.13 зависит от T-067 / PR #152 (1.5.12): input bounds/429 T-067 не должны быть отменены. До human review контракта merge запрещён; обоснование и точный scope — [review doc](../reviews/T-091-client360-run-scope.md).

Добавлены явная страница `/clients/:id`, общий кэш профиля и предварительная загрузка из сигнала, карточки инцидента и HITL. Старые действия Trace сохранены отдельно. Cache key включает клиента, выбранный запуск, окно операций и текущий run для режима current. Секции показывают продукты, маскированные контакты, текущий master-profile риск ухода/CLV, состояние выбранной истории/care_score, рекомендации по общению, операции/сбои, сигналы, инциденты, timeline состояний и назначенные/выполненные подарки. У операций сохраняются копейки, у исторических дат — год. Интерфейс ru/en, обе темы, таблица прокручивается внутри мобильного блока.

Read API заполнен реальными данными в repeatable-read/read-only transaction. По умолчанию baseline + current; `all` выбирается явно, конкретный id даёт baseline + выбранный запуск. При отсутствии current не происходит неявного перехода в all. Окно операций привязано к sim_time/снимку исторического запуска. Decimal проецируется числом для amount/care/hazard. account_closure читается также через churn_events, даже без primary_client_id. Подарки берутся из существующих tasks: autonomous open либо approved/changed/done; предложения, ожидающие HITL, rejected/cancelled исключены. Политика HITL и записи в БД не менялись. Контакты маскируются; безопасное поле city сохранено для совместимости старого regression test.

Ограничение объёма видно в UI: до 50 последних операций/сигналов/инцидентов/подарков и 100 состояний. Профиль/продукты — текущие master records вне запусков; история ограничена выбранной областью. Если в исторической области нет closure, интерфейс сообщает об этом, а не подставляет другой запуск.

Проверки: 9 Client360 vitest cases; 9 production-bundle Playwright cases (0 flaky). Warm click→painted profile: 34,2 мс из сигнала, 32,2 мс из инцидента, 32,3 мс из HITL при пороге 300 мс и одном prefetch API request. Реальная PostgreSQL regression проверяет сим-время 2001 года против wall clock 2026, current/all/history/no-current, closure, реальные gift statuses и подсказки разных стилей. Измеренное покрытие новых executable backend-строк — 96,97 % (32/33); общий clients.py 77,27 %, непокрыт прежний поиск клиентов. Полный `make test`: 1017 backend passed / 22 skipped (unit 733/18, integration 211/2, scenarios 42/2, compliance 31/0), 153 frontend passed. Финальный `make lint` зелёный: ESLint, TypeScript, 153 Vitest, Ruff, mypy (242 modules), OpenAPI drift 191/191. `make sync-contracts` выполнен без нового diff; ORM generation пропущен штатно при пустом DATABASE_URL, поскольку DB-контракт не менялся. После генерации повторены 2 Client360 backend tests — passed. Обе frontend сборки и i18n check (1585 keys) зелёные. Финальный diff проверен на whitespace/errors; cross-layer изменения разрешены координатором.

Скриншоты ru/en/light/dark: `docs/screenshots/client360/client360-{top,history}-{ru,en}-{light,dark}.png`. Browser fixtures проверяют только UI/cache; backend проверяется отдельной реальной PostgreSQL regression на scratch БД с mock LLM. Реальные LLM/почта/Telegram не использовались. Статус `in_progress` сохраняется: обязательны human review contract-change и отдельно не выполненная live GigaChat проверка из общего DoD.
