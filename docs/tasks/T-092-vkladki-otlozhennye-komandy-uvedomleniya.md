# T-092 — Вкладки «Отложенные», «Команды», «Уведомления»

| Поле | Значение |
|---|---|
| Эпик | E7 Рабочее место CX |
| Субагент | `SA-UI-Workspace` (рабочее место CX) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
Спящие обращения с причиной и временем пробуждения; нагрузка команд и дисциплина отчётов; центр исходящих сообщений.

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 2, §8.3, §11.1

## Контракты
- `api/openapi.yaml: signals/deferred, teams/load, notifications`

## Зависимости
- Зависит от: [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md), [T-063](T-063-uzly-followup-monitor-verify-close-gift-i-otlozh.md), [T-037](T-037-sla-dvizhok.md)
- Блокирует: —

## Что сделать
1. Отложенные: таблица с reason/wake_sim/обратным отсчётом; Команды: карточки с open/in_progress/warning/breached/reports_missing и sla_compliance; Уведомления: лента по каналам с предпросмотром текста и статусом доставки (ссылка на Mailpit при включении).

## Критерии приёмки
- [x] Пропущенный отчёт команды виден как reports_missing с подсветкой.
- [x] Фильтр по клиенту в уведомлениях работает из Клиента 360.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/tabs_misc.spec.ts
```

## Отчёт субагента
Ветка `codex/T-092-client-notifications`: Client360→Notifications с client_id и сохранением run scope, строгий invalid-ID отказ, отсутствие старой cached выдачи, сброс только client filter. Найденный actual404 gift_catalog исправлен через существующий useGifts/GET settings/gifts, без изменения подарков/денежных правил/API/DDL. RED12→GREEN24, полный574frontend/80files, eslint/typecheck/обе сборки; native4ru/en×themes+mobile,97fingerprints unchanged/0browserwrites/0external. [Review/proof](../reviews/T-092-client-notifications.md). Reports_missing acceptance и общий exact-head CI остаются gate; карточка не done.

Дополнение freeze: native actual API/UI ru/en×light/dark на main1c022fe показал
12команд,16пропущенных отчётов у5команд; точные reports_due/reports_missing и
text-danger сверены с API, без browser writes/errors/external. Четыре screenshot
и [proof](../reviews/FREEZE-2026-11-03-offline-install-proof.json). Full CI207
зелёный; whole DoD/статус карточки автоматически не повышается этим evidence.
