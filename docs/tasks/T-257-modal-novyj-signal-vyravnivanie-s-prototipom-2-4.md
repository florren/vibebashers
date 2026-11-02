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
- [ ] Сигнал создаётся прежним API; после отправки доступен переход на путь и след.
- [ ] ПДн-подсказка присутствует; микрофон скрыт без HTTPS/localhost (правило 6.5).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npx vitest run src/pages/workspace
cd frontend && npx playwright test e2e/new-signal-modal.spec.ts
```

## Отчёт субагента
Ветка `codex/T-257-new-signal-modal`, отдельный implementation checkpoint от T255192267b. Прежний POSTsignals/DTO сохранён; добавлены city/unknown client/manualID, agent/PII hints, actual result Journey+Trace, typed voice_meta. Native secure context обязателен для VoiceInput; label textarea отделён от кнопки микрофона. Unicode codepoint3..5000 без truncation, существующий Journey label сохранён отдельным ключом. Source-qualified локально498frontend/67files green14.20s,43adjacent green, typecheck/lint и обеproductionbuilds green. Actual browser/HTTP/screenshots и финальная parent composition ещё выполняются; DoD/приёмка не отмечены завершёнными. Денежные/HITL/серверные политики, public API/DDL не менялись.
