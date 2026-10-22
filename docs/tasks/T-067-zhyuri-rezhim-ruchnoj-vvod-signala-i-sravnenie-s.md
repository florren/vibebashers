# T-067 — Жюри-режим: ручной ввод сигнала и сравнение с правилами

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Жюри вводит текст — агент обрабатывает на глазах; параллельно mock показывает, что сделали бы правила.

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 2 (жюри-режим), §12.5, §18 сц. 3

## Контракты
- `api/openapi.yaml: POST /api/signals, POST /api/agent/compare`

## Зависимости
- Зависит от: [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md), [T-065](T-065-trassirovka-zapuskov-i-striming-tokenov.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md)
- Блокирует: [T-109](T-109-panel-ii-protiv-pravil.md), [T-206](T-206-nadiktovat-zhalobu-voiceinput-v-rezhime-pokaza-i.md)

## Что сделать
1. POST /api/signals: создание сигнала origin=jury, выбор клиента или неизвестный; при compare_with_mock — второй запуск kind=compare на mock без побочных эффектов (dry-run инструментов записи).
2. POST /api/agent/compare: синхронное сравнение классификаций с diff.
3. Защита: лимит 10 ручных сигналов/мин, длина ≤ 4 000.

## Критерии приёмки
- [ ] Сценарий 3: от ввода до карточки инцидента ≤ 60 с на Ultra; панель показывает различия с mock.
- [ ] Compare-запуск не создаёт инцидентов и уведомлений.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=jury_input
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
