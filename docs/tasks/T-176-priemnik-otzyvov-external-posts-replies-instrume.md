# T-176 — Приёмник отзывов, external_posts/replies, инструмент publish_public_reply

| Поле | Значение |
|---|---|
| Эпик | E15 Внешние площадки и автономный возврат [BRD] |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Слушатель внешней площадки (BRD FR 1.1) и публикация ответа агента под постом (FR 1.5) с правилами публичного ответа (ТЗ 9.3, 21.2, 21.5).

## Разделы ТЗ (docs/TZ.md)
§3.6, §9.3, §21.2, §21.5

## Контракты
- `api/openapi.yaml: POST /api/public/reviews, GET /api/public/feed*, POST /api/feed/{post_id}/reply, GET /api/feed/stats`
- `events/sim/review.schema.json`
- `db/schema.sql: external_posts, external_replies`

## Зависимости
- Зависит от: [T-171](T-171-mock-abs-scheta-tarify-provodki-sid-i-invariant.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md), [T-032](T-032-shina-sobytij-simulyatora.md), [T-008](T-008-realtime-listen-notify-websocket-hab.md)
- Блокирует: [T-177](T-177-ekran-feed-emulyator-lenty-ploschadki-vidzhet-ab.md), [T-179](T-179-scenarij-8-komissiya-za-qr-oplatu-i-publichnyj-o.md), [T-224](T-224-sborschik-sleda-app-trace-kauzalnyj-obhod-fazy-d.md)

## Что сделать
1. POST /api/public/reviews: пост → external_posts, событие review.posted, сигнал канала review_portal (origin review_portal, external_post_id), запуск агента немедленно независимо от состояния симулятора (ТЗ 4.7, автосоздание run live — T-040 расширение).
2. Инструмент publish_public_reply(post_id, text, link_to_dm): проверка текста на ПДн/номера карт и promise_check; запись external_replies с latency_ms от posted_at; статус поста replied; событие review.replied; топик WebSocket feed.
3. Промпт prompts/v1/public_reply.md: извинение, факт/срок возврата, приглашение в личный канал, без ПДн, тон по сегменту и площадке; при negativity ≥ 80 — review.escalated_to_dm и личное уведомление.
4. Фоновые посты из корпуса SA-Reviews (0–2 в сим-час, настройка); реакция двойника клиента на публичный ответ как комментарий «эмуляция клиента».
5. GET /api/feed/stats по v_feed_latency.

## Критерии приёмки
- [ ] Публикация через API → ответ агента под постом; в тексте ответа нет номеров карт/телефонов (тест на регулярки).
- [ ] review.* валидны по схеме; латентность ответа записана.
- [ ] Пост без идентификации → публичное приглашение в личный канал + сигнал «неидентифицированный».
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_public_reviews.py
```

## Отчёт субагента
Ветка `feat/b06-b16-abs-feed`. `backend/app/feed/service.py`: `create_post` (событие `review.posted`), `link_signal`, `publish_reply` (санитизация ПДн/обещаний, латентность от `posted_at`, статусы `replied|escalated_to_dm`, события `review.replied|escalated_to_dm`), `feed_stats`. Посты создаются для публичных каналов в генераторе симулятора (`_emit_signal`) и в нормализаторе (сценарии, жюри, API); `signals.external_post_id` ↔ `external_posts.signal_id`. API `POST /api/public/reviews` (сопоставление по `client_products.card_last4`), `GET /api/public/feed[/{id}]`, `POST /api/feed/{id}/reply`, `GET /api/feed/stats`. Тесты: `tests/unit/test_feed_sanitize.py`, `tests/integration/test_abs_feed.py`.
