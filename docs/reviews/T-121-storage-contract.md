# T-121: durable storage checkpoint, migration0015

Это подготовленная аддитивная DDL после фактической0014. Окончательное contract
review всего Telegram service ещё впереди; реальные Telegram calls не выполнялись.

`channel_runtime` хранит conversations и inbound receipts с encrypted JSON,
отдельные delivery receipts и per-chat clock. FK в public отсутствуют намеренно:
операционная история не откатывается вместе с bank baseline. Новый
`notifications.delivery_key` UUID с уникальным индексом — неизменная identity
доставки, отличающая новую строку от старой с тем же числовым id.
`pg_dump` исключает channel_runtime, ORM регенерирован штатно (92 класса),
Alembic check на собственной БД не обнаружил новых upgrade operations.
Schema metadata остаётся частью общего baseline contract fingerprint.

InboundStore держит transaction-scoped advisory locks в порядке update→chat.
Одна транзакция содержит handler side effects, draft и receipt. Повтор того же
update/body/chat возвращает cached response; другой body/chat того же update
отклоняется. Отсутствующий response и handler failure откатывают всё. State и
response шифруются pgcrypto с APP_SECRET; placeholder/короткий secret запрещён.
Это механизм обработки, а не обещание exactly-once физической отправки.

`0015` повторяема. Downgrade не удаляет receipts/keys: разрушительный откат может
повторить внешнюю отправку. Операционный откат — выключить Telegram service и
delivery actor, сохранить схему и receipts, затем исправить код; для смены
APP_SECRET понадобится отдельная контролируемая re-encryption процедура.
До финального review route/worker не подключены, поэтому выключение пока не нужно.

Проверки: собственная `cx_t121_transport_revision`, PG16 tools;
6 actual PostgreSQL checks passed2.28s, включая повторное применение SQL,
новый object/connection, ciphertext, concurrent duplicate, rollback/retry,
настоящий dump/restore с receipt, созданным после dump. Archive list не содержит
channel_runtime, ciphertext/receipt/external_ref переживают restore, восстановлен
исходный delivery_key, reused numeric id до restore имел другой UUID.
Это не полный service, OS process restart, maintenance-drain, outbox recovery
или Bot API proof. Они будут проверены после реализации соответствующих модулей.
