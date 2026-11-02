# T039 B: clean storage checkpoint0019

Пользователь подтвердил вариант B для реализации (через root,02.11.2026). Это отдельный packet после T161/T037; финальный concrete DDL/API review остаётся обязательным. Этот checkpoint — **только storage/codec**, не завершённый modelled-prevention runtime.

## Actual chain и точный delta

Parent bed96481 объединяет clean T037/T161 с approved T24170fe/actual0018. Новая0019 имеет down_revision0018. Миграция0017 и её зеркала не менялись; canonical schema расширена только новым tail.

Добавлена nullable `behavior_receipts.details JSONB` без default/backfill. SQL NULL остаётся unknown. Старый app может продолжать писать NULL; отсутствие details не доказывает нулевую prevention. Новый stable PG16 shape validator проверяет version1, точные13ключей, positive integer-not-bool IDs, native kinds, timezone-aware timestamps, согласованность action/consumed_sim и предел2048bytes. Клиентского текста, ПДн и денежных сумм в структуре нет. SQL shape check не выдаётся за proof native lineage: соответствие work/episode/evidence и атомарный writer ещё реализуются отдельно.

Времена разделены: cancellation_sim — существующий logical consumed_sim; cancellation_observed_sim — horizon owner advance; resolution_sim — последняя обязательная native resolution, nullable при неизвестной provenance. Late observation не подставляется вместо actual resolution. First-complaint completeness явная; incomplete/legacy metadata не получает prevention credit. Care/p/delay/RNG, deadlines, dCLTV, платежи и HITL не менялись.

## Доказательства на собственной scratch PG16

До изменения canonical schema БД реально upgraded до0018, details отсутствовал. Создан один явно synthetic legacy receipt. После actual0018→0019 его PK/поля/hash сохранились, details SQL NULL; повтор SQL0019 дважды не изменил строки. Aggregate [proof](T-039-receipts-storage-proof.json) сохранён до fixture resets, raw rows не публиковались.

- Codec + actual PG constraint/idempotency/legacy tests: **44 passed,6.82s** (`/tmp/t039-receipts-storage-final.log`).
- Authoritative make sync-contracts:110ORMклассов, только новый details field/check в generated model; API types без delta, public version остаётся1.5.22.
- Alembic check: **No new upgrade operations detected** (`/tmp/t039-receipts-foundation-drift.log`).
- Ruff/formatter3файла, mypy codec, contracts47schemas/163paths и licenses550 — green. Новых dependencies нет.

BehaviorOwner/Store/facts/runtime и все11 прежних behavior blobs не изменены; hooks не активированы. Modelled summary/API27, cancellation atomic writer, all-causes time/complaint lineage и полный runtime regression ещё впереди. Нельзя объявлять B/T039 завершёнными или считать generic cancelled/Sent предотвращёнными.

## Совместимость/операторская граница

DDL требует штатного migration/maintenance окна: ALTER TABLE/CHECK может ждать receipt writers; production операции не выполнялись. Изменяется DB contract fingerprint, поэтому старые baseline snapshots проверяются действующим compatibility preflight, не получают выдуманную metadata. Downgrade сохраняет audit column/provenance; физический DROP не выполняется. При rollback приложения сохраняют0019 contract/migration knowledge; старый code игнорирует nullable column. Данные/receipts задним числом не переписываются. Root CSI0020 может брать этот clean0019 parent; receipts runtime WIP не требуется.
