# T-188 — Экран /manager: эмулятор планшета и смарт-часов руководителя, ack → HITL

| Поле | Значение |
|---|---|
| Эпик | E16 Аудиомониторинг отделения и мисселлинг [BRD] |
| Субагент | `SA-UI-Compliance` (экраны /compliance, /manager, голосовой ввод [BRD]) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Устройство руководителя с всплывающим алертом (стол, ФИО, суть, цитаты) и кнопками «Иду» / «Ложное» / «Открыть инцидент» (ТЗ 12.2 экран 10, 22.6).

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 10, §22.6

## Контракты
- `api/openapi.yaml: compliance/alerts, alerts/{id}/ack`
- `events/ws/message.schema.json: compliance`

## Зависимости
- Зависит от: [T-186](T-186-schetchik-narushenij-mashina-sostoyanij-sessii-a.md), [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md)
- Блокирует: [T-203](T-203-lokalizaciya-ekranov-v1-3-feed-compliance-manage.md), [T-217](T-217-ui-vkladka-transkripty-na-compliance-zagruzka-sp.md)

## Что сделать
1. features/manager: переключатель формата планшет/часы, лента уведомлений, всплывающий алерт поверх с вибро-анимацией и звуком; кнопки решений → POST /ack; состояние после решения.
2. Открывается по QR из меню демонстратора (T-195) на телефоне; адаптив под 360×640 и круглый экран часов; без роли, X-Role branch_manager.
3. Фильтр по отделению; офлайн-индикатор соединения.

## Критерии приёмки
- [ ] Алерт появляется ≤ 1 с после события compliance.alert; решение видно в HITL инцидента.
- [ ] Скриншоты планшета и часов в обеих темах.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npm run test -- manager
npx playwright test e2e/manager.spec.ts
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
