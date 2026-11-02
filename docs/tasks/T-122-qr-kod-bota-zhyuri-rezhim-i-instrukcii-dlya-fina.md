# T-122 — QR-код бота, жюри-режим и инструкции для финала

| Поле | Значение |
|---|---|
| Эпик | E9 Лендинг, трекинг, Telegram-бот |
| Субагент | `SA-TgBot` (Telegram-бот) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 5 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
На экране и в README — QR на бота и короткая инструкция для жюри.

## Разделы ТЗ (docs/TZ.md)
§11.3, §17 E12

## Контракты
- `api/openapi.yaml: public/bot/qr`

## Зависимости
- Зависит от: [T-121](T-121-telegram-bot-cxpulsecontrolbot-aiogram.md), [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md)
- Блокирует: [T-151](T-151-readme-i-demo-skript.md)

## Что сделать
1. GET /api/public/bot/qr (SVG, кэш); блок «Жюри-режим» в шапке с модальным QR и подсказкой на двух языках; docs/DEMO.md раздел «Бот».

## Критерии приёмки
- [ ] QR читается с проектора (тест на экране 1080p с 5 м — ручной).
- [ ] При выключенном боте блок скрыт.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
curl -f localhost:8080/api/public/bot/qr
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._

## Ревизия: signed readiness и QR (checkpoint)

Изолированная ветка codex/T-122-bot-qr поверх T1217acce1b. Устранён false-positive
health по одному token: running требует свежего signed successful-poll proof
(90реальных секунд) и активного owned delivery task. После restart/rotation/stale
readiness unknown/error; proof ephemeral, не банковский факт и не delivery receipt.
QR ведёт на username реального getMe, серверный SVG cache не кэширует readiness.
UI480px ru/en, hidden disabled/error/no username, loss-ready/image error handled.
API1.5.23 reserved после22; DDL не добавляется. S2S HMAC применён и кheartbeat.

Проверено:24backend unit/ASGI2.81s, actual public PG1pass8.36s;38bot checkpoint
7.62s+3 новых actualSDKgetMe identity cases (повтор ещё выполняется),336frontend
с lint/typegreen. Contracts45/163, drift193, mypy11green. Полный backend/coverage,
UI screenshots, final contractreview, CI/merge ещё впереди. Реальных Telegram
запросов нет. 1080p/5м читаемость — ручной критерий, автоматически не подтверждён.

## Contract-change и evidence перед PR

API1.5.23 добавляет optional health.tgbot_username и signed internal heartbeat;
paired rollout/rollback и потребители описаны в docs/reviews/T-122-bot-readiness-contract.md.
При unavailable UI скрывает QR, старые enum health сохранены. DDL нет.
Source0c4eec0:1661unit/18skip,353frontend+lint/type,50botfake green. Source49f2872
содержит main db1f73c +parent42907e6,26corpus regressions green. Coverage84/85=98.82%
и6actual browser variants source0708fd9 в review artifacts; реальные TG не проверялись.
Final CI и review pending, карточка остаётся in_progress, ручной 1080p/5м критерий
не выдаётся за автоматически проверенный.
