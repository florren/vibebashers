# T-209 — Адаптеры источников ingest_sources: REST, polling-воркер, file; встроенная mock-лента /api/public/mock-social-feed

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-Teams` (симулятор, команды, SLA) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Один канал соцсетей принимается и через REST, и через polling без внешних сервисов (ДТЗ FR-1.2, решение 20.6 п. 28).

## Разделы ТЗ (docs/TZ.md)
§3.7, §13, §16.4

## Контракты
- `db/schema.sql: ingest_sources, ingest_messages`
- `api/openapi.yaml: /api/ingest/sources*, GET /api/public/mock-social-feed, IngestSource, IngestSourceUpdate`

## Зависимости
- Зависит от: [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md), [T-178](T-178-korpus-publichnyh-otzyvov-i-nabor-reviews-v1.md)
- Блокирует: [T-220](T-220-scenarii-10-transkript-roznichnogo-dialoga-i-11.md)

## Что сделать
1. Таблица ingest_sources и сид demo-профиля: rest_default (rest, social), mock_social_polling (polling, url=http://localhost:8000/api/public/mock-social-feed, interval 10 с), file_import (file, data/import/messages/).
2. Polling-воркер (asyncio-задача): по interval_s запрашивает config.url?since=cursor, ожидает массив UnifiedMessage, передаёт в normalizer, обновляет cursor/stats; ошибки — в stats.last_error, backoff; событие ingest.source_polled.
3. Mock-лента: генерирует сообщения из корпуса соцсетей по расписанию симулятора (в т. ч. сценарий 11), стабильные external_id, курсор since.
4. GET/PUT /api/ingest/sources, POST /{code}/poll; is_external=true для URL вне localhost — бейдж в настройках.
5. Тесты: опрос mock-ленты даёт сигналы, повторный опрос — только дубли; выключенный источник не опрашивается.

## Критерии приёмки
- [ ] Сообщение сценария 11 приходит через polling и создаёт сигнал без участия REST.
- [ ] Статистика источника видна в /settings → Источники.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_ingest_sources.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
