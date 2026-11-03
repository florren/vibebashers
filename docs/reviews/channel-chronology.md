# Хронология клиент ↔ Банк: проверка перед фризом

Дата: 03.11.2026. Пакет T-176/T-177, T-119, T-121, T-078; cross-layer согласован
пользователем. API/DDL/events и финансовые правила не меняются.

## Исправления и воспроизведение

1. `/feed` показывал вопрос по `posted_sim`, ответ по `published_at`.
   Теперь обе видимые даты — wall-clock; исходный sim timestamp сохранён
   в tooltip. Это исправляет отображение без переписывания истории.
2. PostgreSQL `now()` равен началу транзакции. Если транзакция ответа
   началась раньше вставки вопроса другой connection, ответ получал более
   раннее время. Публикация поста/ответа использует `clock_timestamp()`;
   latency вычисляется из того же DB instant. API сортирует ответы по
   `published_at,id`. Та же ошибка воспроизведена у общего notify_client
   в шести эмулируемых каналах (6 failed до исправления); sent_at теперь
   также clock_timestamp(). Дедупликация, статусы и санитайзер сохранены.
3. Отложенный Telegram ACK мог записать часы нового, чужого run.
   ACK использует sim clock только собственного current run; иначе
   `sent_sim=NULL`, реальные receipt/sent_at сохраняются. Внешних отправок
   в проверках нет, используется FakeSender.
4. PersonalChat и клиентская дорожка LiveJourney сортировали RFC3339 как строки. Теперь сравнивается instant
   с сохранением PostgreSQL microseconds внутри одной миллисекунды.
   Общий компаратор исключает расхождение двух экранов.
   Проверены разные offsets и порядок вопрос1/ответ1/вопрос2/ответ2.

5. Автоматический подарок использует ctx.sim_time вместо глобальных часов.
   Выбор/размер/условия/HITL и формулы сохранены. Review #213 согласован;
   отдельная история gift уведомлений автоматически не исправляется.

До исправления адресные PG тесты дали 6 failed/1 passed, frontend —
3 failed/5 passed. Дополнительный Journey test воспроизвёл ещё одну
инверсию: 1 failed/15 passed до применения общего компаратора. После исправлений первый PG пакет — 7 passed;
расширенная регрессия clocks/followups/Telegram/personal/fault causality —
52 passed. Финальные новые tests используют штатный ingest normalizer.

## Проверки

- Полный backend unit перед композицией T-078: 2179 passed, 19 skipped, 64.77s.
  Первый запуск с внешним `TGBOT_ENABLED=false` дал 1 failure: эта переменная
  перекрыла временный `.env` проверяемого installer test. Повтор без override
  зелёный; assertions/production code ради этого не менялись.
- Frontend: 580 passed, 81 files; typecheck и обе build (operator/personal).
- Browser: 4 passed, ru/en × light/dark; по три screenshot на вариант.
  Это настоящий Chromium на Feed, PersonalChat и LiveJourney с синтетическими API fixtures, API замокан (не доказательство реальной внешней доставки). POST запрещён перехватом.
  Повтор на compiled assets двух настоящих FastAPI surfaces (operator и
  personal root /): 4 passed, 4.0s. Vite-only proof не заменяет этот повтор.
  CI harness публикует personal только на динамическом localhost port,
  получает адрес через compose port и ждёт /api/personal/health.
  Изоляция/default compatibility harness: 18 unit passed.
  Первый CI дал 4 browser failures из-за неверного origin personal.html;
  assertions/timeout/retries сохранены, исправлен именно адрес сервиса.
- Ruff/formatter, mypy, frontend lint; contracts check: 48 схем, 167 путей.
- Финальная итерация PG: 23 passed, 124.20s (19 новых + 4 effect-time).
  До добавления старых notification transactions: 13 passed, 69.09s; 6 emulated channels через
  штатный normalizer, 3 автора публичного ответа, 4 ACK/run варианта.
  Добавлены 6 старых-транзакций cases для notify_client; итоговый
  После clock_timestamp все шесть проходят в составе финальных 23 tests.
- Дополнительно 5 существующих PG tests feed/gift/terminal gift passed.
- Полный CI PR — отдельный merge gate; локальные проверки его не заменяют.

## Read-only аудит существующей истории

`scripts/reviews/channel_chronology.sql` выполняет один SELECT всех запусков
в одном statement snapshot. Нет текстов, контактов, пользовательских значений;
аудит не изменяет записи. На рабочем локальном стенде получено:

- 4530 доставок с signal anchor: 0 ответов раньше вопроса по real/sim,
  0 foreign run, 0 неизвестных timestamps.
- 580 публичных ответов: 0 ответов раньше post по реальному времени.
  До UI fix все 580 выглядели более ранними из-за разных clock domains.
- 59 дочерних клиентских сообщений: 0 сообщений раньше parent, 0 foreign run.
- 1479 gift notices без signal anchor, все привязаны к собственному incident.
  Одно уведомление имеет sim timestamp раньше первой сохранённой resolution;
  real timestamps совпадают. У остальных 1478 есть предшествующая resolution.
  Поэтому итог `known_invariants_passed=false`: история не объявляется чистой.

Аномалия: notification 25, INC-000155, sent_sim 09.11.2026 06:24Z,
first resolution 12.11.2026 10:24Z. Реальное время обеих записей
01.11.2026 10:10:23.690196Z. Историческая запись не исправлялась.
В gift producer найдено чтение глобального sim_state вместо собственных
часов контекста; причинность именно старой записи этим ещё не доказана.
Timestamp автоматического gift issuance исправлен отдельным diff PR #213
и явно одобрен пользователем после зелёного CI. Его неизменённый production
diff включён в общий PR #212; подробности и RED/GREEN —
`T-078-gift-own-clock.md`. Ручной API исторических задач не меняется и
требует отдельного решения поведения при отсутствии собственных часов.

`sent/delivered` здесь — сохранённый статус эмуляции, не доказательство
внешнего получения. Неизвестные anchors/clocks явно выведены отдельно;
отсутствие известных инверсий не доказывает полноту данных. Аудит timestamps
не доказывает смысловую корректность произвольного LLM-ответа, качество
реального провайдера или 100% покрытия проекта. Для primary history
денежная аномалия остаётся открытой до отдельного решения.

## Откат

Revert PR возвращает отображение/запись timestamps; DDL нет, сохранённая
история не переписывается. Старые некорректные значения автоматически
не корректируются. Рабочий стек этим пакетом не перезапускается.


## Сверка полного nightly прежнего main

Run41611773482 на 518d95d: backend shards и основной smoke зелёные,
nightly дал 2 report browser failures на ru/light и ru/dark. Daily chart
без денежных оценок правильно выводил `cabinet.noSavedEconomics`, а тест
ошибочно требовал подстроку «Нет» с заглавной буквы. Assertion заменён
на точное равенство соответствующему ru/en ключу для каждого chart type.
Проверки отсутствия SVG, JSON/XLSX, scope, read-only и A4 сохранены;
product copy/formulas не меняются, timeout/retries прежние. Полный
изолированный demo/performance + browser повтор запускается на candidate.
