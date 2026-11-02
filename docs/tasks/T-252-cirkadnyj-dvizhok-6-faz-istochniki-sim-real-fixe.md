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
cd frontend && npx vitest run src/shared/theming
cd frontend && npx playwright test e2e/circadian.spec.ts
```

## Отчёт субагента
Ветка `codex/T-252-circadian`; implementation `af8f063`, ordinary merge main `d2a4026`. PR/merge выполняет родительский агент после gates.

Реализованы sim/real/fixed, сезонный offline NOAA расчёт для даты источника, Москва/polar cases, explicit local-only geolocation, общий inline/runtime bootstrap, 8s contrast-guarded interpolation/reduced motion/manual override, ночной декоративный слой и read-only current-run digest с исключениями manager/compliance. Header отдельно исправлен на Europe/Moscow без изменения общего UTC fmtSim.

Контракты/БД/зависимости не меняются; generic settings поддерживает ui.circadian. T-253/T-254 отдельно. Необходимая дискретная смена полярности текста согласована; поверхности переходят непрерывно, foreground guard сохраняет WCAG.

Production synthetic Playwright5/5, actual API/WS Mock-only9 естественных sim.tick ×60; ночь проверена отдельным явным API jump_to, не выдана за естественный переход. Фазовый WCAG36cases +72 directed transitions×101 samples; actual475frames за7924ms, mintext4.500018/control3.0000002. Четыре actual API ru/en light/dark PNG просмотрены и tracked в docs/screenshots/T-252/.

Подробности, границы доказательств, команды и итог полного прогона: [T-252-circadian-verification](../reviews/T-252-circadian-verification.md). Статус остаётся in_progress до полного make test, CI/review/merge; незавершённая приёмка не объявляется готовой.
