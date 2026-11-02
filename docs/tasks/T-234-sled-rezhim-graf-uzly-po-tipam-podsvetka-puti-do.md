# T-234 — «След»: режим «Граф» — узлы по типам, подсветка пути до итога, правая панель-аккордеон

| Поле | Значение |
|---|---|
| Эпик | E23 Поиск и след объекта [АРХ] |
| Субагент | `SA-UI-Trace` (экраны «Путь обращения» и «Поиск и след» [АРХ]) |
| Оценка | M (1–2 дня) |
| Волна | 9 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
Граф-навигация по связям (референс 2, ТЗ 26.6, 28.5): узлы по типам, выбор центра, раскрытие панели с данными объекта.

## Разделы ТЗ (docs/TZ.md)
§28.5, §26.6

## Контракты
- frontend/src/pages/trace/components/GraphView

## Зависимости
- Зависит от: [T-232](T-232-ekran-sled-trace-kind-ref-do-obekt-posle-itog-oz.md), [T-107](T-107-graf-langgraph-s-podsvetkoj-uzla-i-graf-suschnos.md)
- Блокирует: —

## Что сделать
1. Граф: за основу берётся `pages/engine/GraphView.tsx`; React Flow входит в зафиксированный стек (MIT), но в `package.json` пока отсутствует — исполнитель либо добавляет `@xyflow/react` с записью в `docs/LICENSES.md`, либо расширяет собственный SVG-граф, решение обосновывается в PR; узлы — формы и иконки по типу (сигнал, инцидент, клиент, действие, деньги, сообщение), рёбра из `edges[]` с подписью отношения; раскладка слева направо по фазам.
2. Подсветка пути до итогового решения; посещённые узлы — приглушение и галочка (без зачёркивания), выбранный — статичное кольцо; мини-карта.
3. Правая панель-аккордеон «Сводка / Связи / Данные / Переход», раскрытие 400 мс, на узких экранах — нижняя панель; клавиатурная навигация по узлам.
4. Группы веера раскрываются по клику; режим хранится в URL; производительность — до 300 узлов без деградации (виртуализация/кластеры).

## Критерии приёмки
- [x] Граф строится для сценариев 1, 6, 8; клик по узлу центрирует след.
- [x] Нет мигания и внешних ресурсов; доступность с клавиатуры.
- [x] Режим можно отключить без потери остальных.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npx vitest run src/pages/trace/components
cd frontend && npx playwright test e2e/trace-graph.spec.ts
```

## Отчёт субагента
Ветка `codex/T-234-trace-graph`; `cross-layer` согласован пользователем. Contract-change OpenAPI 1.5.16 требует human review до merge. Реализован собственный SVG без новых зависимостей: реальные фазы/рёбра, шесть форм и иконок, directed terminal path, visited/static ring/minimap, клавиатура, responsive accordion 400 мс и URL mode/focus/run scope. Columns сохранён. Все N веера доступны страницами по 50 с actual anchor/phase; основной SVG виртуализирован, старые страницы не накапливаются в cache/DOM. Неизвестные узлы не придумываются, для скрытого родителя есть явная подсказка и ссылка на его след. Новый endpoint default `current`, существующий Trace default `all` и `include=detail` сохранены.

Проверки:
- Полный composed `make test` до bounded ref guard: backend **1406 passed / 22 skipped**, frontend **188 passed**. После guard — **53 targeted unit/PG passed**; финальный `make lint`: 188 frontend, Ruff 353, mypy 254, drift 192 — green. Coverage fanout: **157/159 = 98,74%**.
- Decimal Unicode поддержан; malformed `²`, overflow и пустой путь не вызывают DB/LLM. Общий parser gap записан в audit существующей T-230. Полный walk 1001 событий; 10001-related page50: p95 **122,96 мс**, Python peak **258387 B**; fingerprints всех таблиц неизменны, BombLLM 0.
- **17 Trace UI unit**, **11 production browser** Graph + legacy Trace/Journey. Для 300 synthetic UI nodes: render 262 мс, pan 26 мс, main DOM 6→5, steady-frame p95 16,8 мс. Actual Mock-recorded сценарии 1/6/8: **24 production UI/API variants и 24 PNG**, real center/run scope/visited, GET only, fingerprints всех 85 таблиц неизменны, 0 LLM/remote/page errors.
- Оба builds; i18n 1725 keys; contracts 45/162; sync-contracts и tasks 205 идемпотентны.

Подробности и артефакты: `docs/reviews/T-234-trace-fanout-contract.md`, `docs/reviews/T-234-trace-graph-verification.md`. Полный backend после ограниченного guard не повторялся по согласованному плану; требуется полный PR CI. Generic DoD real GigaChat и human contract review ещё не выполнены, поэтому статус `in_progress` и последний критерий не закрыт. Собственные test servers остановлены; push/PR/merge выполняет родитель.

Перед публикацией: normal merge main `d1710be`; scoped112 tests =53 T-234 +59 redaction passed40,08с, Ruff355/mypy255/frontend ESLint/typecheck green. Четыре actual UI PNG ru/en ×light/dark отслеживаются в `docs/screenshots/T-234/`. Path bounds kind/ref1..40/1..200 и run_id maxLength32/positive bigint явно согласованы в OpenAPI1.5.16/docs, старый Trace не изменён. Полный backend повторно не запускался.


CI perf followup PR172: p95344мс на runner исправляется production eager route metadata compilation через public `app.openapi()` после всехroutes; SQL/testthreshold300/10001/page50/первыйGET не менялись.70startup/ref/fullN/health/WS/real-scenario targets green; неизменённый perf p9554,19мс локально. CI exacthead остаётсяgate. Детали: `docs/reviews/T-234-cold-route-performance.md`.
