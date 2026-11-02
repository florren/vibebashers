# T-255 — Экран «Обзор» /overview: KPI-полоса, индекс CX, микс каналов, поток, решение агента, лента, очередь решений, экономика, сводка смены

| Поле | Значение |
|---|---|
| Эпик | E21 Дизайн-система v2: темы, циркадный режим, «кикубари», каркас и «Обзор» [ПРОТО] |
| Субагент | `SA-UI-Workspace` (рабочее место CX) |
| Оценка | L (3–4 дня) |
| Волна | 9 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
«Обзор» по прототипу 2.4 на реальных API (ТЗ 26.4, 14.1).

## Разделы ТЗ (docs/TZ.md)
§26.4, §26.5, §14.1

## Контракты
- `api/openapi.yaml: /api/metrics/dashboard, /api/metrics/cx-index, /api/metrics/economics/live`
- frontend/src/pages/overview/

## Зависимости
- Зависит от: [T-254](T-254-karkas-v2-bokovaya-navigaciya-sostoyanie-sistemy.md), [T-256](T-256-indeks-cx-i-ryady-potoka-get-api-metrics-cx-inde.md), [T-107](T-107-graf-langgraph-s-podsvetkoj-uzla-i-graf-suschnos.md)
- Блокирует: —

## Что сделать
1. Страница `pages/overview/`: девять блоков из ТЗ 26.4, каждый ведёт на свой экран; значения из существующих API и `cx-index`.
2. Блок «Напряжение клиентов»: индекс CX и проекция сигналов (расстояние — негатив, угол — стабильная функция идентификатора, подпись «проекция, не география»); микс каналов и поток 24 ч (ECharts).
3. Блок «Решение агента»: цепочка шагов выбранного запуска (`decision-chain`), ссылки «Путь» и «След»; очередь решений (3 первых HITL) с переходом в HITL; живая лента.
4. Сворачиваемая «Сводка смены» (текст агента за последние сим-часы, подпись режима), светофор состояния; режимы «Тихий» и «Ситуационный»; таблица соответствия 26.5 для подписей.
5. vitest, e2e, скриншоты обеих тем и пакетов.

## Критерии приёмки
- [x] Ровно блоки ТЗ 26.4; значения совпадают с API; индекс CX считается по формуле 14.1.
- [x] В «Тихом» режиме не более 9 блоков и нет мигания.
- [x] Скриншоты `brand` и `ops`, две темы, два языка.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npx vitest run src/pages/overview
cd frontend && npx playwright test e2e/overview.spec.ts
```

## Отчёт субагента
Ветка `codex/T-255-overview`,9реальных блоков и scoped drilldowns/WS/unknown/exact money. API29/T041/Journey/CSI API28/receipts DDL19 stack обычной композицией уже включены; новый RBAC/денежные/HITL policy не вводятся. Final application source1c9/55c byte-identical по manifest. Make lint485frontend/69files+backend/bot/type/drift green, обе production builds,102targets(66unit+36integration)green60.43s,8/8actual browser9.1s и24PNG. Explicit JourneyFollow/Replay входят в8route GETwalk114tablehashesunchanged; fixture/startup writes вне readonly фазы. Gen2 идемпотентен206cards. Подробности/source boundaries — `docs/reviews/T-255-overview.md`, machine proof и identity manifest рядом. ExactheadCI/parentreview/merge остаются pending; in_progress/общийDoD не закрыт.
