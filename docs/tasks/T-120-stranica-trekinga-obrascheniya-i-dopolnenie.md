# T-120 — Страница трекинга обращения и дополнение

| Поле | Значение |
|---|---|
| Эпик | E9 Лендинг, трекинг, Telegram-бот |
| Субагент | `SA-Landing` (лендинг и трекинг) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Клиент видит понятный таймлайн: принято, разбирается ИИ-ассистент, инцидент создан, команда работает, нужны уточнения, ответ, решено.

## Разделы ТЗ (docs/TZ.md)
§11.2, §11.1

## Контракты
- `api/openapi.yaml: public/track/{token}`

## Зависимости
- Зависит от: [T-119](T-119-lending-potencialnogo-klienta-antibot-proverka-q.md), [T-063](T-063-uzly-followup-monitor-verify-close-gift-i-otlozh.md)
- Блокирует: [T-121](T-121-telegram-bot-cxpulsecontrolbot-aiogram.md)

## Что сделать
1. Страница /track/:token с таймлайном из TrackingView, автообновление (поллинг 10 с или WS без авторизации по токену), форма «Дополнить обращение» при can_append и вопрос агента.
2. Уведомления на странице (эмуляция push) и, при Mailpit, письмо со ссылкой.
3. Тексты без внутренних терминов (error_code, команды) — используется словарь «понятных» статусов.

## Критерии приёмки
- [x] Клиент видит статус «команда работает» ≤ 1 мин после создания инцидента.
- [x] Дополнение создаёт signal.appended и будит отложенное обращение.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/tracking.spec.ts
```

## Отчёт субагента
Ветка `codex/T-120-public-tracking`, stacked от T-119 `85588f2` (`codex/T-119-public-claim`). Реализованы публичный таймлайн ru/en, polling 10 с, уведомление о новом сообщении, вопрос и форма дополнения при `can_append`, сохранение текста и Idempotency-Key при повторе после ошибки. Ошибки страницы не показывают технические детали. Подтверждённый статус работы специалистов виден при следующем polling, без ожидания симуляционного часа.

Backend дополнение атомарно записывает child signal через normalizer и валидное `signal.appended`; повтор UUID не создаёт второй signal/event. Child сохраняет run родителя. AgentService обрабатывает дополнение, пробуждает только ожидание его родителя и восстанавливает потерянный NOTIFY из БД; Путь reply-wakeup не обходит HITL дополнения; существующая timer-политика графа сохранена. Regression проверяет реальный graph с concurrency=1 при неподвижных симуляционных часах и сохранение чужого followup.

Публичная история ограничена деревом сигналов владельца токена: уведомления соседнего клиента того же инцидента и неотправленные черновики исключены; внутренние recipient/client/incident поля не выдаются. Токен скрыт в HTTP/Uvicorn logs и Problem.instance; ответам добавлены no-store/no-referrer/noindex. Для Mailpit добавлен локальный SMTP adapter и `MAILPIT_HOST`/`MAILPIT_PORT`, конфигурация описана в README/.env.example. Письмо содержит личную ссылку, хранимая запись уведомления — безопасный текст без токена. SMTP failure записывается как failed и не имитирует успешную отправку. Реальные почта/Telegram/GigaChat не использовались.

Контракты, generated types и схема БД не менялись. Скриншоты обеих тем и языков: `docs/screenshots/public-tracking/{landing,tracking}-{ru,en}-{light,dark}.png`. Browser fixtures проверяют только UI; DB/agent проверки выполняются отдельно на scratch PostgreSQL с mock LLM.

Проверено: `make lint` (154 frontend tests, Ruff, mypy, OpenAPI drift), `npm run build` (основная и personal сборки), `scripts/i18n_check.py`, Playwright landing/tracking (9 passed), targeted public/followups integration (7 passed), privacy/SMTP/dispatch unit (14 passed). Полный `make test` завершён успешно: unit 736 passed/18 skipped, integration 212 passed/2 skipped, scenarios 42 passed/2 skipped, compliance 31 passed, frontend 154 passed. Окончательное дерево дополнительно проверено: полный unit suite 744 passed/18 skipped, targeted integration 7 passed, targeted privacy/SMTP/dispatch unit 14 passed. Измеренное покрытие добавленных executable backend-строк — 94,38 % (168/178, coverage.py; diff относительно f594c43). Короткий reply при low_confidence остаётся на HITL; regression подтверждает scheduled parent до решения сотрудника и fired после штатного accept/resume, при том же sim_time.

Полная приёмка не отмечена: live GigaChat из AGENTS.md §8 не запускался, поскольку эта ревизия явно ограничена mock LLM и локальными fake transport. Отсутствие live-проверки не скрывается зелёными mock-тестами.


Разбиение 01.11.2026: исходный объединённый snapshot `e63ded4` сохранён без переписывания истории. После T-119 эта ветка добавляет только маршрут трекинга, polling/append UI, signal.appended/reply/HITL wakeup, SMTP/env/README и их regression tests. Production-код и tests итогового стека побайтово совпадают с проверенным `e63ded4`; отличаются только отчёты карточек. Самостоятельные проверки stacked ветки: make lint (154 frontend tests, Ruff, mypy, OpenAPI drift), обе production-сборки, 21 backend privacy/SMTP/dispatch/public/followup regression test и 9 Playwright cases прошли. Все исходные end-to-end assertions и тесты полного snapshot сохранены.

Интеграция с main после PR156: пользователь подтвердил конкретное HITL-поведение PR157. Сохранён parent_id helper _submit_public; дублированный трёхаргументный вариант из merge удалён. Целевые backend12passed8.34s, make lint зелёный333format/246mypy/frontend; итоговый CI ожидается. Реальные email/Telegram не отправлялись.
