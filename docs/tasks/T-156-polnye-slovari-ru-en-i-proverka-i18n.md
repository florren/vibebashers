# T-156 — Полные словари ru/en и проверка i18n

| Поле | Значение |
|---|---|
| Эпик | E13 Локализация |
| Субагент | `SA-i18n` (локализация) |
| Оценка | M (1–2 дня) |
| Волна | 5 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
Все экраны переключаются без «сырых» ключей; форматы дат/чисел/валют по локали.

## Разделы ТЗ (docs/TZ.md)
§12.4, §20.1 п. 11

## Контракты
- frontend/src/shared/i18n

## Зависимости
- Зависит от: [T-010](T-010-ui-mastera-nastrojki-9-shagov-i-ekran-nastrojki.md), [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md), [T-090](T-090-kartochka-incidenta.md), [T-106](T-106-zhivaya-trassirovka-agenta.md), [T-119](T-119-lending-potencialnogo-klienta-antibot-proverka-q.md), [T-130](T-130-ui-benchmarkov.md), [T-133](T-133-ekran-kalkulyator-poter-dopuscheniya-v-stile-biz.md)
- Блокирует: [T-203](T-203-lokalizaciya-ekranov-v1-3-feed-compliance-manage.md)

## Что сделать
1. Сбор ключей (i18next-parser), перевод en, глоссарий терминов (инцидент/incident, сигнал/signal, SLA, HITL); make i18n-check: отсутствующие/лишние ключи = ошибка; Intl для дат (сим-время с пометкой), чисел, ₽.

## Критерии приёмки
- [ ] i18n-check чист; Playwright не находит «сырых» ключей в en и ru.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make i18n-check
```

## Отчёт субагента
Ветка `feat/T-156-i18n-en`, PR не открывался. Полный словарь `en.json` в паритете с `ru.json` (блоки `claim.*` и `bench.*` сохранены), переключатель языка в шапке, форматы дат, длительности, миллисекунд и ₽ по локали. Контракты не менялись.
