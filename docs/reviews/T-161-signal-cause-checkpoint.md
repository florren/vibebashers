# T-161 — already-complained signal cause

Root technical signoff реализован без новой таблицы/версии схемы: настоящий
canonical classifier после record_step в той же graph/checkpoint TX записывает
source intent. Owner проверяет actual AR/signal/run/client, schema-valid
classification и canonical step score_pipeline; свободный agent request или gold
metadata сами episode не открывают. Отрицательный sentiment либо canonical
churn_intent/repeat flag допускают факт уже поступившей жалобы. Нейтральные
info_request и gratitude без этих flags остаются без complaint episode.

Такой source не получает выдуманный failed-op FK. Membership хранится в existing
receipts `source_kind=signal, action=cause:<episode>`. Первый receipt предшествует
единственному patience uniform; p_complain/delay не разыгрываются задним числом.
Повторный intent/новое соединение не меняет patience/RNG. Signal native timestamp
сохраняется как first complaint; logical hazard начинается с очередной UTC
границы после признания факта, прошлые неизвестные hazard ticks не доигрываются.
Repeat deadline использует исходное received_sim, но эффект не предшествует
моменту признания/уже сохранённой истории состояния. Реальные следующие cause
memberships добавляются в открытый episode без нового initial draw.

Causal read поддерживает bounded same-run/client parent lineage, без циклов.
SLA/resolution и notifications используют реальную signal/incident связь; все
signal causes должны быть resolved перед закрытием episode. Agent requested
satisfied/retained/churned всё ещё не является resolution/account closure.

Combined actual PG: **27 passed, 190.23 s** (8 новых source cases и прежние19
runtime/owner). Проверены negative/neutral/gratitude/explicit flag/noncanonical
gold, dedup/new connection, ровно один patience draw, rollback/shared RNG,
foreign/baseline scope и actual Mock graph classifier. Первый actual graph input
оказался neutral по неизменённому Mock lexicon; для negative acceptance выбран
однозначный негативный текст, pipeline/порог/assertion не ослаблялись.

Это checkpoint, не full suite/OS-process/archive доказательство. Следуют
signal-only resolution, native generator integration и OS-process equivalence.
Policy enabled=false, legacy churn_risk и финансовые формулы не менялись.
