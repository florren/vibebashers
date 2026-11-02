# T238 — prerequisite физической projection для T262

Проверенный defect: Mock возвращал `product_line=deposits`, но normal/instant
producer сохранял только classification JSON. `v_cabinet_signal_facts` использует
`signals.product_line_code`, поэтому native обращение не попадало в кабинет/отчёт.

Общий `app.agent.classification_store.save` сохраняет classification и FK-known
physical code в том же caller TX. Отсутствующий/unknown/ambiguous code даёт SQL NULL;
coarse product не используется для догадки. Normal/instant paths вызывают один helper.
Refresh/effect-time fences, human wait, решения/платежи/формулы, prompt/schema и
кассеты не менялись. Mock unique mapping отдельно использует canonical справочник;
`debit_card` относится к нескольким направлениям и не превращается в debit_cards.

Независимый editorial physical source сохраняется только при совокупности native
baseline ownership, FK-known кода, exact seed_annotation, accepted same-run seed
ingest и совпадающего seed_instance, per-run receipt с seed/reference_anchor/offset/hash.
CSI дополнительно требует actual csi_response. Raw API/scenario annotation, одно
kind=baseline, missing/mismatched receipt/source/instance не дают исключения. Новый
модельный output/step сохраняется честно, без выдачи его за editorial разметку.

Проверки:9 native PG cases projection/provenance, включая настоящий Mock → physical
column → manager-scoped overview/JSON/XLSX с конкретным native ref и read-only
fingerprint; существующий completed/refund instant test дополнен проверкой honest
ambiguous NULL. В итоговом focused coverage T262 helper имеет7/7 executable lines,
100%. Это не benchmark accuracy основного провайдера и не завершение всей T238.

DDL/HTTP API/зависимости не меняются. Rollback source возвращает прежний producer;
массового backfill/переписывания существующих rows нет. Рабочие БД не затрагивались.
