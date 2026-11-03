# T-257 — Модал «Новый сигнал»: выравнивание с прототипом 2.4 и кнопка «Показать путь»

| Поле | Значение |
|---|---|
| Эпик | E21 Дизайн-система v2: темы, циркадный режим, «кикубари», каркас и «Обзор» [ПРОТО] |
| Субагент | `SA-UI-Workspace` (рабочее место CX) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 9 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Единая точка ручного ввода сигнала (канал, город, текст) с подсказкой, напоминанием о ПДн и переходом на экран пути (ТЗ 12.2 п. 7, 27.4).

## Разделы ТЗ (docs/TZ.md)
§12.2, §27.4, §26.4

## Контракты
- frontend/src/widgets/JuryModal.tsx
- frontend/src/shared/routes.ts

## Зависимости
- Зависит от: [T-226](T-226-ekran-put-obrascheniya-journey-ref-stepper-iz-8.md)
- Блокирует: —

## Что сделать
1. Привести существующий модал к раскладке прототипа 2.4: канал, клиент/«неизвестный», город, текст, подсказка «агент определит тональность и маршрут», запрет ПДн, «Надиктовать» (VoiceInput).
2. После отправки — карточка результата с кнопками «Показать путь» (`/journey/:ref`) и «Показать след»; сигнал создаётся прежним способом через нормализатор.
3. i18n ru/en, доступность, vitest и e2e.

## Критерии приёмки
- [x] Сигнал создаётся прежним API; после отправки доступен переход на путь и след.
- [x] ПДн-подсказка присутствует; микрофон скрыт без HTTPS/localhost (правило 6.5).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npx vitest run src/pages/workspace
cd frontend && npx playwright test e2e/new-signal-modal.spec.ts
```

## Отчёт субагента
Ветка `codex/T-257-new-signal-modal`, финальный runtime/API31 source48fb40f. Полный functional UI, сохранение формы при resize, native secure origin и fail-closed STT defaults реализованы. API31 добавляет только422Problem `/api/stt/test` поверх API30; explicit browser opt-in сохранён, implicit external fallback удалён. `make lint`555frontend/79files,325mypy,drift196/196; обе production builds;15backend unit/HTTP,1actualPG fake-STT; actual production browser5/5 ru/en×themes/mobile,13PNG. Ни реального mic/STT, ни external calls. Полный backend/exact-head CI/parent review остаются обязательны; overallDoD не отмечен. Подробности: [review](../reviews/T-257-new-signal-modal.md), [proof](../reviews/T-257-proof.json).
