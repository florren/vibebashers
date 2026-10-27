# T-157 — Язык коммуникаций с клиентом и en-шаблоны

| Поле | Значение |
|---|---|
| Эпик | E13 Локализация |
| Субагент | `SA-i18n` (локализация) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 5 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Ответ клиенту на языке его обращения; шаблоны и тексты бота/трекинга на en.

## Разделы ТЗ (docs/TZ.md)
§12.4, §11

## Контракты
- `db/schema.sql: notification_templates.lang`

## Зависимости
- Зависит от: [T-015](T-015-shablony-uvedomlenij-spravochnik-podarkov-stavki.md), [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md), [T-121](T-121-telegram-bot-cxpulsecontrolbot-aiogram.md)
- Блокирует: —

## Что сделать
1. Определение языка сигнала (normalize) → выбор шаблона lang; en-версии всех шаблонов; тексты трекинга/бота по языку пользователя; проверка promise_check для en-формулировок.

## Критерии приёмки
- [ ] en-сигнал в жюри-режиме получает ответ на английском; тесты шаблонов на двух языках.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_templates.py -k en
```

## Отчёт субагента
Ветка `feat/T-157-en-templates` от main `b86ec7e`. Ревью APPROVE (Note про быстрый путь и явный language=en, без доработки).

Сделано: `communication_lang` (кириллица → ru, латиница без кириллицы → en, иначе ru); en-близнецы клиентских шаблонов; сид пишет `lang` и при конфликте обновляет subject/body/variables; в `FORBIDDEN_PHRASES` только английские запреты; `render_template`/`notify_client` выбирают lang и откатывают en→ru; акт, подарок, трекинг и бот после текста берут язык сигнала. Поле решения остаётся `text_ru`, подписи трекинга — в `label_ru`. `team_notice` и тексты Problem русские. `refund_fee`, лимиты и контракты не менялись.

Отклонения: нет.

Проверки: `pytest tests/unit/test_templates.py -k en` — код 0, 14 passed; `pytest tests/unit/test_router_tools.py` — код 0, 22 passed. `pytest tests/unit` — код 1, чужой `test_cassettes_have_no_secrets` (кассета gigachat.jsonl). `make lint` — код 2, ruff format на файлах вне пакета. `check_owners.py --base main` — код 1, cross-layer из плана и неотслеживаемый `data/baseline` (пакет его не писал). `make test` целиком не запускался: интеграция и сценарии требуют `DATABASE_URL_TEST`. Страница `/track` в браузере не открывалась: маршрута нет (T-120).

Контракты не затронуты. Время: сессия разработки T-157.
