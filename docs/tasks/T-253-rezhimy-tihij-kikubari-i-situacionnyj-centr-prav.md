# T-253 — Режимы «Тихий» (кикубари) и «Ситуационный центр»: правила анимаций, полоса приоритетов, undo/confirm, тест ≤ 9 блоков

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
Принцип «кикубари» как проверяемые правила интерфейса (ТЗ 26.3).

## Разделы ТЗ (docs/TZ.md)
§26.3, §12.1

## Контракты
- frontend/src/shared/components/PriorityStrip
- frontend/src/shared/components/UndoToast
- frontend/src/shared/ui/motion.ts

## Зависимости
- Зависит от: [T-251](T-251-tokeny-i-pakety-tem-semanticheskie-tokeny-pakety.md), [T-089](T-089-doska-i-tablica-incidentov-s-indikatorami-sla.md)
- Блокирует: [T-242](T-242-ekran-kabinet-menedzhera-produkta-cabinet-kpi-ka.md), [T-254](T-254-karkas-v2-bokovaya-navigaciya-sostoyanie-sistemy.md), [T-258](T-258-vizualnaya-regressiya-i-a11y-pakety-tem-rezhimy.md)

## Что сделать
1. Настройка `ui.attention` = `calm` («Тихий», по умолчанию для кабинета и менеджера продукта) | `control_room` («Ситуационный центр», по умолчанию для демонстратора и пакета `ops`); токены длительностей (250–400 мс), запрет мигания чаще одного раза в 3 с, подъём карточки 2 px, раскрытие вниз.
2. `PriorityStrip` вместо бегущей строки: до трёх пунктов, ручное переключение; метка SLA за 4 часа (`settings.sla_warn_hours`) в списках и карточках.
3. Обратимость: `UndoToast` (8 с) для локальных действий интерфейса, подтверждение с описанием последствий для необратимых серверных (HITL, закрытие инцидента) — без изменения серверных правил.
4. Словарь «ошибок без обвинения» и тёплых пустых состояний в i18n ru/en; тест `data-block ≤ 9` для экранов кабинета и «Обзора»; линт-правило против `animation: infinite` вне разрешённого набора.

## Критерии приёмки
- [ ] В «Тихом» режиме нет мигания и звука (исключения 12.1 сохраняются); тест блоков зелёный.
- [x] Undo и confirm работают согласно разделению локальных/серверных действий.
- [x] SLA-метка за 4 часа появляется в списках.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npx vitest run src/shared
cd frontend && npx playwright test e2e/calm-mode.spec.ts
```

## Отчёт субагента
Ветка `codex/T-253-attention-modes`; код `59da3d3` + `747bd92`, обычная композиция `bd649f2`. Полный backend1663/22skip и frontend311 на59; финальный frontend312 +actual4calm/4SLA-mobile. Backend/contracts не менялись. Подробности и безопасный GET materialization finding: [T-253-attention-modes.md](../reviews/T-253-attention-modes.md). Снимки: `docs/screenshots/T-253/`. Human review UI HITL confirmation и применение budget к реальным T242/T255 остаются открыты; done не выставлен.
