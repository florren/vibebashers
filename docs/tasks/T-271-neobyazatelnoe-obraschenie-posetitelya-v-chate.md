# T-271 — Необязательное обращение посетителя в чате

| Поле | Значение |
|---|---|
| Эпик | E9 Лендинг, трекинг, Telegram-бот |
| Субагент | `SA-Landing` (лендинг и трекинг) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 9 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `done` |

## Цель
GitHub #101: посетитель :9999 может представиться свободно, сохраняя анонимность.

## Разделы ТЗ (docs/TZ.md)
§11.4, §12.2

## Контракты
- `api/openapi.yaml: PersonalSession/PersonalMessageBody/PersonalHistory`

## Зависимости
- Зависит от: [T-269](T-269-izolirovannyj-anonimnyj-chat-9999-i-tunnel-tuna.md)
- Блокирует: —

## Что сделать
1. Необязательное display_name до 120 символов: UI ru/en, валидация, своя история и восстановление.
2. Имя в метаданных нормализованного сигнала и контексте агента, вне контактов банковской идентификации.
3. Idempotency, удаление подписи, изоляция сессий, безопасный текст, regression и браузер.

## Критерии приёмки
- [x] Можно назвать себя произвольно либо оставить поле пустым; подпись восстанавливается и безопасно отображается.
- [x] Имя учитывается в контексте агента, анонимность и ui_pers_demo сохранены.
- [x] Регрессии и ru/en light/dark/mobile проверены.
- [x] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make lint && make test
frontend lint/typecheck/test/build; Browser :9999
```

## Отчёт субагента
Ветка `codex/seed-safety-visitor-name`, GitHub #100/#101. Cross-layer L1/L2/L3/L4 и contract-change согласованы заказчиком; PR и merge после CI прямо запрошены.

T-270: --if-needed не меняет существующие таблицы/настройки/архивы; реальные ошибки 2/3/4, pg-tools до записи, client 16 в Docker из подписанного PGDG. На копии текущего стенда неизменны все 85 таблиц. На чистом PostgreSQL 16 coverage 480/480 и настоящий dump/restore (200 клиентов). История стенда не пересоздаётся, старое coverage показывается предупреждением.

T-271: необязательное имя/псевдоним, сохранение собственной подписи и истории, safe text, контекст агента без банковской идентификации. OpenAPI 1.5.7 и generated TS; миграций нет. Новых Python/npm-зависимостей нет, лицензия PG client записана.

[Проверки и скриншоты](../benchmarks/seed-visitor-2026-10-30/README.md): regression seed error/preserve, API/session/idempotency, ru/en light/dark/mobile, ответы mock-агента. Реальный GigaChat и установка на стенде проверяются после merge, без reset.

Локально: make lint/test (588 unit, 121 integration, 22 scenarios; 21 skip), дополнительно 31 compliance; frontend 132 passed. Финальный targeted 31 passed, coverage 88%; contracts/drift/i18n/owners успешны. Скриншоты обеих тем/языков приложены.
