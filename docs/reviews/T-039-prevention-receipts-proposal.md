# T039/T161: modelled prevented-by-resolution (decision proposal)

Статус: предложение, **DDL/runtime не реализованы**. Ownership: T161 owner;
source review получен от владельца, это не user financial/policy approval.
Номер будущей additive миграции назначает root отдельно;0017 задним числом
не менять. T039 сейчас честно сообщает prevented=null/not_modelled.

## Факты текущей модели

`_care` меняет score, Sent не отменяет primary complaint. После успешного native
p_complain draw durable pending primary work уже означает запланированную
жалобу; `_complaint` не делает второй Bernoulli. Есть только две точки cancellation:
`_resolution` после ALL-causes resolved guards и `_agent_intent` после уже
поступившей canonical complaint. kind repeat/patience не являются новой primary
жалобой. В controlled120/90/30 реально cancelled10 именно из already-complained,
а не из90Sent. Generic cancelled count не равен prevention.

`behavior_work` хранит episode/kind/due/status/consumed_sim; `behavior_receipts`
имеет свободные source_kind/action и PK(run,client,source_kind,source_id,action),
но не cancellation reason/evidence details. Историю нельзя восстановить догадкой.

## Минимальный additive вариант

Использовать existing receipts с source_kind=work/source_id=work.id и typed
`action=cancelled_by_resolution|already_complained`. Optional bounded versioned
`details` JSONB — additive колонка future migration; old receipts остаются NULL.
Не строить новую очередь/таймер, не менять p/delay/care/retention/formula.

Details содержит только native references/times, без текста клиента/ПДн:
version, episode_no, work_kind, due_sim, cancellation_observed_sim,
first_complaint_sim_at_cancellation, reason evidence id/kind/source_id,
actual resolution_sim (nullable при неизвестном времени источника).
`consumed_sim` receipt сохраняет cancellation/observation semantics; поздний
observation tick не выдаётся за actual resolution time. Для resolution source
используется native behavior_evidence reference с проверкой incident/run/client;
для already_complained — canonical signal reference.

Receipt и изменение work.status фиксируются атомарно одной owner TX. До записи
проверяются positive IDs, same run/client/episode, pending row lock и native
cause/evidence lineage; uniqueness препятствует double-count после restart.
Нельзя задним числом заполнить reason для legacy cancelled rows автоматически.

## Точная предлагаемая аналитическая семантика

Modelled prevented-by-resolution учитывает DISTINCT(run,client,episode,primary
work) только если одновременно:

- primary complaint work действительно pending после исходного p_complain draw;
- до cancellation нет first canonical customer complaint;
- существующие `_resolution` ALL-causes guards прошли на actual native evidence;
- actual resolution_sim известен и строго раньше due_sim;
- recorded cancellation reason — resolution с полным verified receipt.

Повторные жалобы, patience, already_complained, простое Sent/care, неизвестный
resolution time, равенство due и resolution, foreign cause/episode и legacy
cancelled без details не кредитуются. Это **не** attribution уведомлению.
Care→p_complain policy не вводится. Экономический prevented_loss_rub и ставки
не выводятся из этого нового count: existing dCLTV formula не меняется.

Отчёт отдельно показывает eligible recorded modelled count, completeness/source
и unknown legacy cancellations. При неполной provenance — nullable unknown,
не выдуманный0. Известный0 допускается лишь для полностью наблюдаемого окна без
eligible prevention receipt; pending future timers остаются отдельным фактом.

## Проверки до принятия реализации

- Pending primary + verified all-causes resolution до due/first → один receipt;
  retry/restart/два owner дают тот же один count, без дополнительных RNG draws.
- Already complained (в том числе текущие10), repeat/patience, due equality,
  resolution после due, unknown timestamp и mixed/unresolved/foreign causes не
  увеличивают prevention. Same timestamp observation не заменяет native source.
- Cancellation и receipt rollback вместе; невозможен orphan/count без work.
- Legacy NULL details читаются unknown; старый app может продолжать писать NULL,
  новый report не заявляет completeness. Нужны source/DB fingerprint и baseline
  regeneration по действующим правилам, без silent conversion старых receipts.
- Controlled model evidence проверяется без изменения p/care/thresholds,
  реальных LLM/Telegram/email или выдуманных customer/gold traces.

## Решение для final review

Вариант A: принять явное уточнение acceptance T039 — отчёт честно содержит
null/not_modelled и реальные Sent/care/complaint/timer facts; prevention attribution
остаётся отдельной карточкой, T039 не приписывает себе90предотвращённых.

Вариант B: согласовать описанную узкую additive provenance и новое аналитическое
определение modelled prevented-by-resolution, реализуемое владельцем T161 с
future migration и конкретным DB/financial/user review. Это самостоятельная
семантика отчёта; текущий implementation approval T161 values её не покрывает.
