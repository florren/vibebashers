# T-201 — Панель «Log/Debug» как общий компонент демо-экранов

| Поле | Значение |
|---|---|
| Эпик | E8 «Под капотом» |
| Субагент | `SA-UI-Engine` («Под капотом») |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Компактная лента шагов текущей обработки с задержками, уверенностями в %, JSON-сущностями, правилами, tool calls и бизнес-строкой — для /feed, /compliance, /manager и карточки инцидента (ТЗ 12.6).

## Разделы ТЗ (docs/TZ.md)
§12.5, §12.6

## Контракты
- `events/ws/message.schema.json: agent, agent_tokens, compliance, abs`
- `api/openapi.yaml: agent/runs/{id}`

## Зависимости
- Зависит от: [T-106](T-106-zhivaya-trassirovka-agenta.md), [T-008](T-008-realtime-listen-notify-websocket-hab.md), [T-065](T-065-trassirovka-zapuskov-i-striming-tokenov.md)
- Блокирует: [T-177](T-177-ekran-feed-emulyator-lenty-ploschadki-vidzhet-ab.md), [T-187](T-187-ekran-compliance-split-screen-transkribacii-sche.md)

## Что сделать
1. shared/components/LogPanel: источники — топики agent/compliance/abs по фильтру (signal_id | session_id | post_id); строки с временем, задержкой, моделью/провайдером, % уверенности, сворачиваемым JSON с подсветкой; ссылки «открыть в Под капотом»; тумблер «скрывать системные промпты».
2. Бизнес-строка эффекта: из ExternalPostDetail.effect_line_ru / incident_economics; для компаенса — стоимость случая.
3. Режим показа: панель развёрнута по умолчанию; производительность — виртуализация списка; i18n.

## Критерии приёмки
- [ ] Панель переиспользуется на трёх экранах без дублирования кода.
- [ ] Первое событие появляется ≤ 2 с после триггера (кассета).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npm run test -- log-panel
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
