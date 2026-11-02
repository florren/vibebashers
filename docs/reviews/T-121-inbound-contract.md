# T-121: проект API1.5.20 и durable диалога

Service-to-service HMAC исключение одобрено пользователем. Окончательный контракт
всего PR ещё не согласован: service/worker/Compose/full checks пока в работе.
Внешних Telegram calls не было.

Новый POST `/api/internal/tgbot/inbound` требует положительные int64 bot_id/chat_id,
неотрицательный int64 update_id, kind и text≤4000. Boolean/float/overflow не
принимаются. Старые kind start/is_client/not_client/free_text/contact/region/append
сохранены, добавлены message/callback. **Даже старые callers должны добавить
bot_id/update_id и HMAC headers**: это изменение входного контракта. Неподписанные
запросы больше не принимаются. До rollout обновить оба transport ends вместе;
предыдущего настоящего tgbot service в репозитории не было.

HMAC проверяется ASGI middleware до JSON/Pydantic/DB, по точным body bytes,
method/path и timestamp±60с. Duplicate security headers отклоняются. Максимум body
32768 bytes. 401/409/413/503 имеют Problem response; configured=false даёт503.
Namespace должен совпадать с текущим bot token. HTTP redirects backend-клиента
выключены, token/secret не входят в repr/logs/response.

`accepted=true` — commit draft+receipt+notification+outbox, а не физический send.
Повтор bot_id/update_id с тем же body/chat возвращает тот же response и не
создаёт notification заново. Другой body/chat —409. Порядок stage хранится в
зашифрованной БД, не в process memory. `/start`, `/status`, `/lang ru|en`,
`/bind CL-…`, `/unbind` работают через тот же receipt. CL — только вымышленный
клиент из демонстрационного UI, не доказательство личности реального человека.
Другой чат не перепривязывает существующего клиента. Перед созданием signal
binding проверяется заново; signal binding использует id+run+tracking token+chat,
а не последний сигнал по числовому id. Неизвестные callbacks, включая manager
accept/reject, не исполняют HITL. T-189 будет рассмотрен отдельно.

Bot language берётся из Telegram либо явного /lang. Tracking URL строится из
operator-configured TGBOT_PUBLIC_BASE_URL, а не docker hostname. В notifications
сохраняется безопасный текст без capability token; полный wire payload и response
зашифрованы. Все replies queued с sent_at/external_ref=NULL до delivery worker.

Проверки текущей реализации:39ASGI/signature unit passed3.58s (actual app,
запрещён любой DB connect на rejects); 7legacy signed public/storage PG passed10.43s;
3new actual message/callback dialog PG passed17.35s: новый app/connection,
duplicate/conflict, ru/en preference, private tracking link, namespace receipts,
stale signal/client binding, чужой чат и explicit unbind. Fake aiogram SDK tests
33passed6.02s; после explicit TGBOT_ENABLED preflight —34cases (итоговый вывод
фиксируется отдельно). Mypy9backend и5bot files green.
Это ещё не проверка настоящей физической доставки, fullmake, OS-restart процесса,
worker drain или contract approval. Ничего из этого не объявляется завершённым.

Полный backend unit после main0011/schema9 и исправления private-unit setup:
**1562 passed /18 skipped за46,39с** (`/tmp/t121-post-inbound-full-unit-v2.log`).
Первый сборочный прогон остановился при collection: старый T157 unit импортировал
удалённый process-global `_bot_drafts`. Его setup переведён на явный draft и новые
обязательные identifiers; прежние assertions ru start/en free text сохранены,
14template unit passed1.02s. Не сохраняем мёртвую global state ради private test.
Физическая доставка и общий fullmake всё ещё впереди.
