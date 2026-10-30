# T-270 — Безопасный повторный seed и pg_dump в Docker

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-Infra` (инфраструктура, установка, realtime) |
| Оценка | M (1–2 дня) |
| Волна | 9 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `done` |

## Цель
GitHub #100: сохранить текущие данные при install и явно обрабатывать ошибки seed/baseline.

## Разделы ТЗ (docs/TZ.md)
§4.4, §4.6, §16.2

## Контракты


## Зависимости
- Зависит от: [T-003](T-003-install-sh-ustanovka-odnoj-komandoj.md), [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md), [T-269](T-269-izolirovannyj-anonimnyj-chat-9999-i-tunnel-tuna.md)
- Блокирует: [T-272](T-272-dobavochnyj-csi-remont-staroj-istorii.md), [T-276](T-276-sovmestimost-starogo-baseline-formata-pg-dump-18.md)

## Что сделать
1. Режим --if-needed: существующие данные/настройки/снимки только читать, явно сообщать coverage и незавершённый seed.
2. Не скрывать exit 2/3/4; проверить pg_dump/pg_restore до записи, включить совместимый клиент 16 в Docker.
3. Regression всех таблиц и baseline bytes; настоящий PostgreSQL 16, первичная и повторная установка, backup стенда без reset.

## Критерии приёмки
- [x] Повтор установки сохраняет данные, настройки и baseline; старое неполное coverage явно показано.
- [x] Ошибки первичного seed/baseline имеют ненулевой код и останавливают install.
- [x] pg_dump/pg_restore 16 доступны, реальный dump/restore и локальный стенд проверены.
- [x] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make lint && make test
docker build; seed --if-needed на копии и install.sh без reset
```

## Отчёт субагента
Ветка `codex/seed-safety-visitor-name`, GitHub #100/#101. Cross-layer L1/L2/L3/L4 и contract-change согласованы заказчиком; PR и merge после CI прямо запрошены.

T-270: --if-needed не меняет существующие таблицы/настройки/архивы; реальные ошибки 2/3/4, pg-tools до записи, client 16 в Docker из подписанного PGDG. На копии текущего стенда неизменны все 85 таблиц. На чистом PostgreSQL 16 coverage 480/480 и настоящий dump/restore (200 клиентов). История стенда не пересоздаётся, старое coverage показывается предупреждением.

T-271: необязательное имя/псевдоним, сохранение собственной подписи и истории, safe text, контекст агента без банковской идентификации. OpenAPI 1.5.7 и generated TS; миграций нет. Новых Python/npm-зависимостей нет, лицензия PG client записана.

[Проверки и скриншоты](../benchmarks/seed-visitor-2026-10-30/README.md): regression seed error/preserve, API/session/idempotency, ru/en light/dark/mobile, ответы mock-агента. Реальный GigaChat и установка на стенде проверяются после merge, без reset.

Локально: make lint/test (588 unit, 121 integration, 22 scenarios; 21 skip), дополнительно 31 compliance; frontend 132 passed. Финальный targeted 31 passed, coverage 88%; contracts/drift/i18n/owners успешны. Скриншоты обеих тем/языков приложены.
