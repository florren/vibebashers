# T-062 — Узел act: коммуникации клиенту и командам

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Исполнение решения через инструменты: инцидент, уведомления, задачи, followup; публичный ответ + личный канал для соцсетей.

## Разделы ТЗ (docs/TZ.md)
§6 шаги 3–4, §8.4, §11.1, §3.6

## Контракты
- `events/agent/decision.schema.json`
- `db/schema.sql: notifications`

## Зависимости
- Зависит от: [T-061](T-061-uzel-decide-sla-marshrutizaciya-prioritet-politi.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md)
- Блокирует: [T-039](T-039-proaktivnaya-vetka-sboj-uvedomleniya-zatronutym.md), [T-063](T-063-uzly-followup-monitor-verify-close-gift-i-otlozh.md), [T-067](T-067-zhyuri-rezhim-ruchnoj-vvod-signala-i-sravnenie-s.md), [T-119](T-119-lending-potencialnogo-klienta-antibot-proverka-q.md), [T-121](T-121-telegram-bot-cxpulsecontrolbot-aiogram.md), [T-157](T-157-yazyk-kommunikacij-s-klientom-i-en-shablony.md), [T-174](T-174-bystryj-put-agenta-uslovnoe-rebro-act-instant-st.md), [T-213](T-213-router-instrumenty-route-to-department-notify-cu.md)

## Что сделать
1. Последовательность: инцидент/связка → уведомление клиенту (первый ответ в SLA сегмента) → уведомление команде → задачи → followup; идемпотентность при повторном входе из чекпоинта.
2. Тон по сегменту (шаблон + корректировка моделью при необходимости, затем promise_check).
3. Для неидентифицированных — ответ на трекинг-страницу/бота.

## Критерии приёмки
- [ ] Сценарий 1: клиент получает первый ответ в пределах SLA сегмента; команда вкладов — уведомление с error_code.
- [ ] Повторный запуск узла не дублирует уведомления.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=deposit_promo_rate
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
