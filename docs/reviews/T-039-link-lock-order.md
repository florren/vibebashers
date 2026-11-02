# T039: linker lock order и controlled 120/90/30

## Проверенный defect и candidate

Concurrent 30 customer graphs с существующим AgentService concurrency=4 дали
25 failed: поздний `create_task(kind=gift)`/resume guard требует `FOR UPDATE`,
когда соседние linkers уже удерживают FK `KEY SHARE` после INSERT
`incident_signals`. Другой linker ждёт первый incident UPDATE. Это cycle
повышения lock, не утверждение, что любой INSERT/UPDATE всегда deadlock.
Исходный log: `/tmp/t039-mass-proof.log`; isolated two-connection follow-on
full-row guard: `/tmp/t039-link-gift-upgrade-regression.log` (DeadlockDetected).

Candidate: scope SELECT в existing `link_signal_to_incident` берёт
`FOR NO KEY UPDATE OF i` **до** FK INSERT/link/mass/economics. Он сериализует
linkers, остаётся совместимым с audit FK KEY SHARE и повторно проверяет same-run
signal/incident после ожидания. Duplicate INSERT остаётся ON CONFLICT DO NOTHING.

Полный `FOR UPDATE` в начале отвергнут: `post_abs_refunds` сперва обновляет
account, затем пишет incident audit с FK KEY SHARE. Ранний полный row lock
создавал бы incident→account / account→incident cycle. Human API и порядок gift
после refund loops не менялись. Existing run SHARE → incident linker lock;
`link`/dCLTV не берут SimState/account lock. Fast refund создаёт новый собственный
incident, не поднимает lock существующего shared ticket.

Весь normal act после link проверен: `_render_client_text` — DB template,
promise_check — детерминированный feed sanitizer; notify/publicreply — local DB
или Telegram outbox, gifts/tasks/followups/state evidence — DB. LLM complete
вызывается normalize/classify/decide до act; HTTP/LLM под новым linker lock нет.
Сохраняются обычный checkpoint commit, human decisions, refund/gift guards.

## Доказательства

- Event-controlled 2 connections: первый linker останавливается после FK INSERT;
  второй фактически блокируется до своего INSERT; first commit → second success,
  два customer links, mass/affected 1/1. Затем выполняется реальный full-row
  gift/resume guard, без создания подарка.
- Actual `post_abs_refunds` handler + real Mock-АБС/PG triggers: human account
  UPDATE удерживается, agent link → account wait; human audit FK проходит,
  human commit освобождает account, затем agent full-row guard проходит.
  Request scope внедрён собственным test run/time; ASGI/network не используется.
  Synthetic refund ровно10, баланс +10, один refund и один human audit;
  duplicate request не создаёт повторных эффектов.
- Controlled mass case: прежние concurrency4 и все30 inputs сохранены;
  120 actual same-run YuFO failed clients, один internal service normal graph,
  90 consented native Sent/emulated chat до первого customer input;
  production behavior loader/capture/engine дают care_score>0 тем же90.
  Все30 жалоб связываются с одним incident, mass/экономический affected120;
  2 human decisions остаются pending, ledger агента пуст.
  Следующий native owner tick фиксирует first_complaint у30, не у service anchor.
- После owner tick actual timers: complaint cancelled10/pending40,
  patience pending120, repeat pending30. Cancelled10 появились после уже
  поступивших жалоб и **не являются** предотвращёнными жалобами.
  Prevented complaints: `null/not_modelled`, не Sent90 и не cancelled10.

3 actual-PG cases passed/28.42s; полный unit1800 passed/18 skipped/54.18s;
Ruff и mypy tool зелёные. Финальный duplicate/старый ABS target фиксируется
следующим checkpoint. Full всей T039/exact-head CI ещё не заявляются.

## Границы proof и оставшаяся работа

Fixture расширяет существующим seed_clients metadata с200 до5000 synthetic
clients; это не полный demo history/baseline proof. Выбираются120 разных actual
YuFO клиентов с активной debit_card. Согласия90/30 и preferred chat заданы только
controlled fixture. Fault schedule содержит существующий native duration90;
policy p/delay/severity/thresholds не менялись. Все deliveries emulated, не реальные
Telegram/SMS/email. Production lite должен fail preflight при insufficient_cohort,
а не повторять клиентов или объявлять3 inputs как120.

Production YAML scenario6 пока inject3: phased source/state/restart interface
будет отдельным proposal до реализации. Acceptance whole T039 не закрыта.
Дополнительный provenance proposal позволит измерять modelled
prevented-by-resolution без attribution уведомлению; сейчас такого receipt нет.

Этот lock/source-cohort diff входит в обязательный financial+HITL final review;
предыдущие approval других PR его не покрывают. DDL/лимиты/цены/права не менялись.

Окончательный duplicate assertion + прежние ABS ledger/feed regressions:
5 passed/30.65s (`/tmp/t039-final-lock-abs-pg.log`), production source тот же.
