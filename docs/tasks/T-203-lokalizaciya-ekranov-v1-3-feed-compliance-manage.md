# T-203 — Локализация экранов v1.3 (feed, compliance, manager, демо-меню) и тексты алертов/публичных ответов

| Поле | Значение |
|---|---|
| Эпик | E13 Локализация |
| Субагент | `SA-i18n` (локализация) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 5 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

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

## Ревизия T-203: статические подписи и bilingual templates

Ветка codex/T-203-compliance-i18n от main1df0024. Устранены hardcodedВСП/стол/Сотрудник/с в Manager, Compliance и LiveMeeting. Все новые подписи через ru/en i18n. Добавлен отсутствовавший misselling_clarification ru/en в данных; не подключена автоматическая отправка, HITL/decision rules не меняются. Public_reply ru/en уже существовали. Сохранённые цитаты/summary_ru источника не переводятся.

Проверки:35catalogunit passed0.52s, actualPGseedtemplate1passed5.84s, actualMockscenario09 1passed6.05s. make lint green(173frontend/Ruff352/mypy251/drift191), i18n1690, productionbuild green. Browser12desktop+2narrowEnglish сочетания,0external/0mutation/0pageerror,85tablefingerprints unchanged. PNG/provenance:docs/screenshots/T-203/; proof:docs/reviews/T-203-browser-proof.json.

Full make test выполняется; exact-head CI/окончательный отчёт ещёобязательны. Узкий320px viewport не выдаётся за отдельную реализацию устройства-часовT188. ЖивойGigaChat/Telegram не вызывались, genericliveDoD этим не закрыт.

Финальный локальный full77fd5c4:1115unit/18skip +240integration/2skip +42scenario/2skip +31compliance +173frontend, exit0(1428backend/22skip). После ordinarymerge maindfbf47a: make lint188frontend/Ruff360/mypy256/drift192,85targetunit2.92s, i18n1728/TSidempotent green. Review:docs/reviews/T-203-localization.md. ExactheadCI ещёобязателен доmerge.
