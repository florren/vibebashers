# T-252 — Циркадный движок: 6 фаз, источники sim/real/fixed, локальный расчёт солнца, 8-секундные переходы, без «вспышки»

| Поле | Значение |
|---|---|
| Эпик | E21 Дизайн-система v2: темы, циркадный режим, «кикубари», каркас и «Обзор» [ПРОТО] |
| Субагент | `SA-UI-Design` (токены, темы, циркадный режим, режимы интерфейса [ПРОТО]) |
| Оценка | M (1–2 дня) |
| Волна | 8 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
Интерфейс «дышит» вместе с днём (ЕТЗ 10, ТЗ 26.2) без внешних зависимостей.

## Разделы ТЗ (docs/TZ.md)
§26.2, §4.1

## Контракты
- frontend/src/shared/theming/circadian.ts
- frontend/index.html (встроенный скрипт)

## Зависимости
- Зависит от: [T-251](T-251-tokeny-i-pakety-tem-semanticheskie-tokeny-pakety.md)
- Блокирует: [T-258](T-258-vizualnaya-regressiya-i-a11y-pakety-tem-rezhimy.md)

## Что сделать
1. Модуль `circadian.ts`: таблица шести фаз; источники `sim` (по умолчанию и на защите — 20.7 № 67; сим-часы из WebSocket `sim`), `real` (часы устройства; восход и закат по формулам положения солнца, сезонность), `fixed`; запасное расположение — Москва; геолокация только по явному согласию.
2. Интерполяция CSS-переменных за 8 с (допуск 5–10 с), `prefers-reduced-motion` — мгновенно; ручной выбор побеждает и сохраняется.
3. Встроенный скрипт в `index.html` ставит `data-pack`, `data-mode`, `data-phase` до отрисовки (нет «вспышки»); тест на отсутствие смены атрибутов после гидратации.
4. Ночной слой: звёзды и луна ≤ 0,08 прозрачности, `aria-hidden`; панель «Ночной дайджест» критических сигналов без всплывающих уведомлений; исключение для `/manager` и `/compliance`.
5. Юнит-тесты фаз и границ (сим/реальное), контраст для всех фаз × пакетов.

## Критерии приёмки
- [x] Смена фазы плавная 8 с; ручной выбор побеждает автоматику; без API-ключа и сети.
- [x] WCAG-контраст проходит во всех фазах; «вспышки» нет.
- [x] Режим `sim` меняет фазы при ускорении ×60.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npx vitest run src/shared/theming/circadian
cd frontend && npx playwright test e2e/circadian.spec.ts
```

## Отчёт субагента
Ветка `codex/T-252-circadian`; runtime/source 8747523, окончательная tested composition 18ad9fd (ordinary merge main dfbf47a и user-approved PR167 dependency42b6d3e). Push/PR/merge выполняет родитель после gates.

Реализованы все 5 пунктов: sim/real/fixed, сезонный offline NOAA расчёт даты источника, Москва/polar/midnight cases, explicit local-only geolocation, единый inline/runtime bootstrap, 8s WCAG-guarded interpolation, reduced motion/manualinstant/persistence, ночной слой и current-run digest с manager/compliance exceptions. Header отдельно показывает Europe/Moscow без изменения общего UTC fmtSim. Late settings GET не обрывает WS-переход; cache digest не показывает прежний run и хранит только public IDs.

Собственных backend/DDL/contract изменений и новых npm-зависимостей нет; существующий generic settings поддерживает ui.circadian. PR167 prefix 9 — отдельная одобренная dependency; обходов валидации нет. T253/T254 отдельно. Необходимая дискретная смена полярности foreground согласована; поверхности переходят непрерывно.

Проверки versioned: полный c71make test backend 1486/22 skipped + frontend 286; после bounded fixes/source 18 make lint frontend: 292/292+Ruff 365+mypy 257+drift 192, обе production сборки; contracts: 45/162, i18n: 1750, TS/tasks: 205 idempotent. Production synthetic5/5(14.8s), реальный Mock-only API/WS complete:9 natural×60ticks morning→noon, затем отдельно pause+jump_to→night,0errors/external/geo. 473 frames / 7906 ms min text 4.5000129 / control 3.0000002. Все 36staticcases/72directedtransitions×101samples и более200000solarboundaries проходят.

4 новых actual API ru/en light/dark PNG source 18 просмотрены и tracked в docs/screenshots/T-252/. Исторические c71/874 не подменяют новые доказательства. Отдельный общий rollback/cache defect передан родителю/P1 и не включён в T252.

Подробности, точные границы доказательств и воспроизведение: [T-252-circadian-verification](../reviews/T-252-circadian-verification.md). Статус in_progress до dependency merge, exact-head CI/review/merge; общий liveGiga DoD — родительский gate.
