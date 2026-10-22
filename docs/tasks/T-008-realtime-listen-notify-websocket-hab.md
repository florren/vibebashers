# T-008 — Realtime: LISTEN/NOTIFY → WebSocket-хаб

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-Infra` (инфраструктура, установка, realtime) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Единый канал живых обновлений для всех экранов по схеме ws/message.

## Разделы ТЗ (docs/TZ.md)
§12.3

## Контракты
- `events/ws/message.schema.json`
- `api/openapi.yaml /ws/stream`

## Зависимости
- Зависит от: [T-004](T-004-karkas-fastapi-konfig-logirovanie-oshibki-health.md), [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md)
- Блокирует: [T-031](T-031-simclock-sim-state-i-upravlenie-simulyaciej.md), [T-065](T-065-trassirovka-zapuskov-i-striming-tokenov.md), [T-077](T-077-uzel-wait-human-ochered-hitl-i-vozvrat-resheniya.md), [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md), [T-106](T-106-zhivaya-trassirovka-agenta.md), [T-108](T-108-lenta-izmenenij-bd-schetchiki-tablic-prosmotr-st.md), [T-144](T-144-proverka-proizvoditelnosti-profilya-demo.md), [T-176](T-176-priemnik-otzyvov-external-posts-replies-instrume.md), [T-177](T-177-ekran-feed-emulyator-lenty-ploschadki-vidzhet-ab.md), [T-201](T-201-panel-log-debug-kak-obschij-komponent-demo-ekran.md)

## Что сделать
1. app/realtime/notify.py: слушатель каналов sim_events, db_activity, agent_stream, incidents, notifications; парсинг payload, маршрутизация в топики.
2. app/realtime/ws.py: /ws/stream, команды subscribe/unsubscribe/ping, фильтры, heartbeat 20 с, монотонный seq, backpressure (дроп agent_tokens при отставании > 500 сообщений).
3. Публикация со стороны приложения: функция publish(topic, type, data, sim_time) с pg_notify (payload ≤ 7 КБ, иначе ссылка id).
4. frontend/src/shared/api/ws.ts: реконнект с экспоненциальной паузой, дозагрузка по since_*/seq, интеграция с TanStack Query (инвалидация).

## Критерии приёмки
- [ ] Сообщения валидны по ws/message.schema.json (тест).
- [ ] Задержка от INSERT в signals до сообщения клиенту ≤ 1 с на профиле demo.
- [ ] Разрыв соединения восстанавливается без потери состояния UI.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_ws.py
```

## Отчёт субагента
Коммит B01. `app/realtime/hub.py` (подписки/фильтры/темы, формат сообщений по `ws/message.schema.json`, текстовые JSON-кадры), `app/realtime/ws.py` (`/ws/stream`: hello → subscribe/unsubscribe/ping, heartbeat 20 с; `/ws/audio/{session_id}` закрывается 1011 до T-181), `app/realtime/notify.py` (мост LISTEN → WS с реконнектом и бэкоффом; таблица канал→топик, envelope `sim_events` маршрутизируется по семейству события). Тесты: `test_app_skeleton.py::test_ws_subscribe_and_ping`, `test_realtime_route.py`. Отклонения: мост поднимается в lifespan только при `APP_ENV≠test`; интеграционный тест NOTIFY→WS на живой БД — в B03 вместе с первым `pg_notify` симулятора.
