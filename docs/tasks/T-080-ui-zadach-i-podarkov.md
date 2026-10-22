# T-080 — UI задач и подарков

| Поле | Значение |
|---|---|
| Эпик | E6 HITL и подарки |
| Субагент | `SA-UI-Workspace` (рабочее место CX) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `done` |

## Цель
Вкладка задач: подарки на подтверждение, звонки, ручные проверки, напоминания об отчётах.

## Разделы ТЗ (docs/TZ.md)
§8.5, §12.2 экран 2

## Контракты
- `api/openapi.yaml: tasks/*`

## Зависимости
- Зависит от: [T-078](T-078-podarki-raschet-zadachi-vydacha-posle-podtverzhd.md), [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md)
- Блокирует: —

## Что сделать
1. Таблица с фильтрами kind/status, действия approve/change/reject/done, выбор подарка из справочника с обоснованием.

## Критерии приёмки
- [ ] Изменение подарка отражается в уведомлении клиенту и в экономике инцидента.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/tasks.spec.ts
```

## Отчёт субагента
Ветка `feat/b17-tasks-stt-env`. `backend/app/api/tasks.py`: список с фильтрами и счётчиками, готовность (`ready`: инцидент решён или when = now), решения approve / change / reject / done; выдача подарка = уведомление клиенту по шаблону `gift_offer` + флаг `gift_issued` у инцидента; замена проверяет каталог и сегмент. `frontend/src/pages/workspace/TasksTab.tsx`: фильтры, «Выдать все готовые», модалка замены подарка. Тест `tests/integration/test_tasks.py`.
