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
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
Частично в PR «L4: фронт»: словарь `frontend/src/shared/i18n/ru.json` (все строки UI, enum-значения API через `tEnum` с фолбэком на код), `scripts/i18n_check.py` (валидный JSON, нет пустых значений, покрытие enum signal_type/flag/sentiment/complexity/criticality/severity из common.schema.json) — в CI job tests шаг i18n теперь строгий; `make i18n-check` дополнительно сверяет TS-типы с OpenAPI. **Отложено:** en-словарь и переключатель языка (демо на русском).
