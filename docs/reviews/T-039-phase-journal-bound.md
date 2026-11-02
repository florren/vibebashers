# T039 API25: bounded native phase journal prerequisite

Typed `scenario.proactive_*` family добавляется в envelope + EventBus registry;
source schema `sim/scenario_proactive`, version1, generated Pydantic models.
Runtime phase producer/source mode этим checkpoint ещё не активированы.
Контракт входит в обязательный API25/event human review перед merge.

Phase evidence не копируется целиком в каждое событие: prepared хранит120
operation IDs; notified — reference prepared + actual anchor/AR + до120 native
notification IDs; complaints — phase refs +30 customer signal IDs; completed —
phase refs + incident/care count; failed — bounded diagnostic enum. Никаких
сырых LLM/errors, customer texts, contact data, secrets или truncated evidence.
Anchor появляется после первого native clock step, поэтому prepared не требует
ещё несуществующий signal ID; notified ссылается на фактический AR/anchor.

Фактический верхний sample — все IDs max signed bigint, UUID max, максимально
длинный native datetime. EventBus payload storage и notification сравниваются
полностью, не только по count. UTF8 envelope bytes:

- prepared2916;
- notified3033;
- complaints1207;
- completed676;
- failed567.

Каждый <8000byte PostgreSQL NOTIFY limit, без обрезки/переименования IDs.
Schema отвергает121операцию, повторные ID, evidence другой фазы, raw error и
ID вне signed bigint до SQL. 40 unit/examples/freshness passed,19 skipped
(12.54s), source schemas46/OpenAPI162 paths, генерация own checkout/models110.
Ранний focused payload test:10 passed/0.09s. Реальный PG16 LISTEN/NOTIFY отдельно
roundtrip всех5 payloads; это protocol-only custom channel, synthetic max IDs
не пишутся в sim_events и не выдаются за operational evidence/LLM traces.

Compatibility: existing families/fields сохранены, новых API paths/DDL нет.
Строгий старый envelope validator не знает scenario family, поэтому rollout
требует согласованного обновления contracts/backend consumers. LLM
classification/decision schemas не менялись; новые live recordings не нужны.
Полные T039 lint/test/CI/coverage остаются за final phase/runtime composition.
