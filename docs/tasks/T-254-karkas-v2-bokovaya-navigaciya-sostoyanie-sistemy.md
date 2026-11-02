# T-254 — Каркас v2: боковая навигация, состояние системы, полоса приоритетов, горячие клавиши, флаг ui.layout, перенаправления маршрутов

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
Каркас прототипа 2.4 (ТЗ 26.4) за флагом без регрессий.

## Разделы ТЗ (docs/TZ.md)
§26.4, §12.2

## Контракты
- frontend/src/widgets/Shell.tsx
- frontend/src/widgets/Sidebar
- frontend/src/app/App.tsx

## Зависимости
- Зависит от: [T-251](T-251-tokeny-i-pakety-tem-semanticheskie-tokeny-pakety.md), [T-253](T-253-rezhimy-tihij-kikubari-i-situacionnyj-centr-prav.md)
- Блокирует: [T-255](T-255-ekran-obzor-overview-kpi-polosa-indeks-cx-miks-k.md), [T-258](T-258-vizualnaya-regressiya-i-a11y-pakety-tem-rezhimy.md), [T-259](T-259-lokalizaciya-v1-5-ru-en-dlya-ekranov-puti-sleda.md)

## Что сделать
1. `Sidebar` с группами «Операционный контур», «Контроль и аудит», «Демонстрация», «Продукт и сеть» (таблица ТЗ 26.4), видимость по пресету роли, сворачивание ниже 1024 px (off-canvas).
2. Верхняя панель: сим-часы с фазой и меткой запуска, LIVE, Старт/Пауза, скорость, «Новый сигнал», строка поиска (подключается `GlobalSearch`, T-231, когда готова), роль, тема; карточка «Состояние системы» (агент, каналы, бейдж `live|replay|mock`).
3. Горячие клавиши `1–6`, `/`, `Ctrl+K`, `?`; справка по клавишам; флаг `ui.layout = v2`, старые маршруты через перенаправления, `/` → `/overview` только при v2.
4. Регрессия: существующие e2e и vitest зелёные в обоих значениях флага; скриншоты до/после.

## Критерии приёмки
- [x] Без флага интерфейс не изменился; с флагом — каркас v2, все старые маршруты работают.
- [x] Меню адаптивно (1920/1440/1024), клавиатурная навигация, `aria-label` на иконках.
- [x] Нет внешних ресурсов.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npm test -- --run && npx playwright test e2e/shell-v2.spec.ts
cd frontend && npx playwright test
```

## Отчёт субагента
Ветка `codex/T-254-shell-v2`, stacked поверх T-253 `e61ce53`; runtime `18de30f`. Флаг legacy(default)/v2, реальные settings, Sidebar4группы/локальные пресеты+Undo, health/demo, shortcuts, adaptive320–1920, query-preserving routes. Frontend325, make lint/2builds green; source80f legacy49+actual4=53 green, final actual4/4 и legacy3204/4.16PNG+proof: `docs/screenshots/T-254/`. Backend/contracts неизменны, full1663/22skip на идентичном backend source59; повторный full backend не заявляется. Подробный отчёт: [T-254-shell-v2.md](../reviews/T-254-shell-v2.md). T242/T249/T255 availability остаются временными зависимостями all94, без fake KPI/закрытия их приёмки; ждём human UI-HITL review T253 и finalCI. Cross-layer L5: новый `frontend/e2e/shell-v2.spec.ts` (согласовано пользователем); root создаёт PR/push/merge.
