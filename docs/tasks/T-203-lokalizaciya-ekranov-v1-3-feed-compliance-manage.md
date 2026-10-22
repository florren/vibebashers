# T-203 — Локализация экранов v1.3 (feed, compliance, manager, демо-меню) и тексты алертов/публичных ответов

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
Полные словари ru/en для новых экранов; шаблоны public_reply и misselling_clarification на двух языках (ТЗ 12.4).

## Разделы ТЗ (docs/TZ.md)
§12.4, §21.5, §22.6

## Контракты
- frontend/src/shared/i18n/*.json
- `db/schema.sql: notification_templates`

## Зависимости
- Зависит от: [T-177](T-177-ekran-feed-emulyator-lenty-ploschadki-vidzhet-ab.md), [T-187](T-187-ekran-compliance-split-screen-transkribacii-sche.md), [T-188](T-188-ekran-manager-emulyator-plansheta-i-smart-chasov.md), [T-195](T-195-menyu-demonstratora-skrytaya-knopka-statusy-prov.md), [T-156](T-156-polnye-slovari-ru-en-i-proverka-i18n.md)
- Блокирует: —

## Что сделать
1. Ключи для новых экранов и состояний; make i18n-check без пропусков; en-варианты шаблонов; проверка длины строк на экране часов.

## Критерии приёмки
- [ ] make i18n-check зелёный; скриншоты en для трёх экранов.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make i18n-check
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
