# T241 — проект контракта API 1.5.22 / DDL18

Пакет требует `contract-change`, `cross-layer` и human review по AGENTS §5.1/7: затрагиваются новый публичный DTO и аудит человеческих решений. Денежные формулы, решения HITL, разрешения и лимиты не меняются.

## Предлагаемый diff

- Типизированные `CabinetOverview`, `CabinetSignals`, `CabinetRoles`; новый read-only `GET /api/cabinet/signals` (sort/date/region, filters, limit≤200, bounded offset). `run_id=current` включает baseline + current; отсутствие current не снимает scope. `all` — явное действие. Период от sim_time, группировка Europe/Moscow.
- Preset headers — фильтр, не RBAC: cx_lead по умолчанию; product_manager с обязательным направлением, product_head с настроенным набором. Soft можно снять явным `product_line=all`; strict возвращает 403 при попытке выйти из набора, включая report T244. Unknown role/run/filter syntax — 422 до запросов данных.
- Nullable деньги и доли при неизвестном покрытии, рядом числитель/знаменатель; никакого вызова compute_incident. Источники — только catalog projection T240; текст маскируется shared privacy helper. Неопределённое направление не выводится из текста/gold.
- SQL review copy: `T-241-ddl-proposal.sql`; canonical migration — actual0018 после0017. Два fact views без размножения; два индекса; nullable actor_role с CHECK семи presets, legacy NULL без backfill. Старый v_cabinet_kpi неизменен (runtime consumers не найдены).
- `actor_role` для новых human_decisions/incident_status_history: header preset при решении/ручном переходе; actor_ref/decided_by остаются исходной меткой сотрудника. Ошибочная роль не приводит к записи. GET отдаёт nullable поле. Это происхождение ручного действия, не утверждение личности. Автоматические действия не получают человеческий preset задним числом.

## Зависимости и временная схема

Normal merge T240 5d128ac, P1 98f57eb и T254 39d21074. API22 зарезервирован root. На раннем checkpoint фактическая DDL17 ещё не была получена: Alembic chain остаётся0014, DDL18 будет только после normal merge реального0017. По отдельному разрешению root targeted PG выполняется на собственной cx_cabinet_revision: upgrade0014 + предложение SQL, без фиктивной Alembic revision. Финальная проверка обязательна повторно на настоящем0018.

## Проверки

Checkpoint: contracts45/paths163; 52 scoped tests (28 pure unit +24 actualPG/API) green15.19s на0014+proposal. Проверены strict/soft, report guard, run isolation, pagination/filters/privacy, nullable saved economics, fanout dedup, actor_role labels и GET fingerprints всех public tables. EXPLAIN ANALYZE aggregate regression без correlated SubPlan; mypy11модулей green. Это provisional setup, не окончательный actual0018 proof. Demo p95/full suite/coverage ещё не выполнены. Никакой полной приёмки не заявлено.

## Фактическая DDL18

После normal merge actual0017 `28c26f8` оформлены canonical/mirror SQL и Alembic0018→0017.
Upgrade18 аддитивный и идемпотентный. Downgrade удаляет только два read-only views и два
индекса, сохраняет actor_role columns/values: происхождение аудита нельзя потерять при
откате кода. Физический drop требует отдельного решения и экспорта. Root согласовал
эту границу rollback. ORM сгенерирован из canonical schema, 110 классов, без ручной правки.

Exact provisional52 at9955a0d отдельно от actual18: 53 tests passed17.07s, fresh18,
два reapply без изменения table fingerprints, actual downgrade17→upgrade18 сохраняет
actor_role. Coverage actual18:200/207 executable lines (97%),53tests55.92s.
Верхняя оценка производительности на demo и full suite остаются отдельным незакрытым этапом.

После bounded config guards:58targeted tests passed16.73s; malformed cabinet visibility/product_head config возвращает409, неизвестный binding422. Ранее coverage97% относится предшествующему source, точные полные проверки следуют после freeze.

## Финальные уточнения API22 до публикации

- `CabinetRegion.identified_clients` и `identified_signals` — известная часть наблюдений.
  `affected_clients` nullable при хотя бы одном неидентифицированном сигнале;
  настоящий пустой cohort сохраняет известный0. Никакой записи/пересчёта денег.
- CSI: `branch_known`, `wait_known`, nullable `branches`, среднее только по заполненным
  ожиданиям. Общие visits не приписываются направлению, новый индекс CSI не выдумывается.
- Неизвестные platform codes агрегируются в один `platform=null` bucket, без URL.
- Compliance officer по отсутствующему `red_words` получает OR по существующим
  `red_word`, `classification.signal_type=legal_regulatory`, связанному same-run
  `incidents.incident_type=misselling`. `red_words=true` — только красные слова,
  `false` явно снимает presentation preset. Overview остаётся статистикой направления.
  DTO роли сообщает `default_compliance_filter`. Это не RBAC и не новый бизнес-класс.
- Полный audit manual writers включает compliance `ack_alert`: nullable actor_role
  из validated `X-Cx-Role`, прежний `X-Role`/actor_ref/decided_by не меняются.
  Прямые automatic service calls оставляют actor_role=NULL. Поле — **заявленный UI
  preset, не проверенная личность**. FSM, решения HITL, платежи и формулы не меняются.

## Версионные проверки и границы доказательства

- Полный gate на frozen8c7801e: unit1738passed/18skip; integration423passed/4skip,
  11failed за2432.05s. Причины:10 lifecycle/durable tests не поддерживали новые
  composite FK actual17;1 legacyfixture пыталась создать дубликат уже под unique17.
  Это **не** зелёный полный `make test`.
- Root разрешил узкие producer corrections без всего T161 runtime WIP:
  `25ee046` cherry→ad57cbe (ordered composite pairs, AND joins, один purge statement),
  legacyfixture exact6lines→ed565b3. T1218line run lease guard сохранён до metadata
  и проверен новым guard-before-metadata case (7132aad). Target15passed77.31s,
  включая исходные10 lifecycle failures и4новых composite/foreign/двухклиентных case.
- API22quality/manual+automatic compliance/demo5000/legacy target65passed79.12s;
  после OR preset следующий target65passed72.29s (legacy case проверялся отдельно).
  demo fixture проверяет реальные5000clients,25GET p95<300 с первым GET, read-only
  table fingerprints, NULL→known coverage, три ветки OR и explicitfalse.
- Ранний actual route benchmark на byte-identical backend8c7801e из UIa3868b3:
  demo5000/2813signals,25GETeach, bank p95 38.42ms, direction22.46ms,
  maxpayload40607B,107table fingerprints неизменны, BombLLM0.
  Networkguard запрещал внешние соединения; отдельный counter попыток не измерялся.
  После quality полей benchmark/EXPLAIN повторяются, ранние числа не выдаются за новые.

Откат release: сначала откатить/выключить cabinet code, затем downgrade18 убирает
только views/indexes. Auditcolumns и их значения остаются; upgrade возвращает views.
Физический drop audit данных не входит в rollback и требует отдельного решения.
Оставшиеся локальные phases и composed проверки завершены ниже; полный CI и human review ещё ожидаются.

## Финальный локальный checkpoint после main 73425c9

Source `42f2488` (обычный merge main, без изменения кабинетного backend):
- оставшиеся фазы на предшествующем byte-identical cabinet source `e4ac976`: unit **1747 passed / 18 skipped** (51.15 s), scenarios **43 / 2 skipped** (255.03 s), compliance **31** (122.36 s), tgbot **33** (6.17 s);
- composed `make lint` green: frontend **354**, Ruff **445** formatted, mypy **292** source files, bot **11** formatted / **5** mypy, OpenAPI drift **193 / 193**, missing/extra 0;
- actual0018 cabinet API/PG + scope target **65 passed** (139.35 s с coverage): **213 / 217 lines, 98%** пяти новых модулей, manual/automatic audit и anonymous/CSI coverage проверены;
- `make sync-contracts contracts-check`: ORM110, **45 схем / 163 paths**, source generation без diff; `gen_tasks.py` дважды — **205** cards, второй запуск без нового diff (нормализована одна пустая строка отчёта T240);
- повторный final backend benchmark на собственной demo5000/2813signals DB: 25 actual GET каждого scope с первым GET; bank p95 **40.49 ms**, direction **24.15 ms**, payload max **45 291 B**; **107** public/private fingerprints unchanged, BombLLM **0**, внешних попыток **0**. `T-241-demo-performance.json` содержит безопасный EXPLAIN ANALYZE/BUFFERS read-only proof.

Это составное локальное доказательство, а не утверждение, что весь `make test`
одним финальным запуском зелёный: исходные 11 failures и их адресные corrections
сохранены выше. CI exact head остаётся gate. Реальный GigaChat не вызывался по
заданию родителя; его сценарная проверка DoD здесь не заявляется.

Перед merge требуется human approval API1.5.22 / DDL0018 / actor_role semantics.
T244 report остаётся 501 по своей карточке; guarded report scope проверен (403/422).

## Review base и DAG

Временная local ветка `codex/T-241-contracts17-base` —
`97fec2220579b7f8f6262906e905543460fff839`: fd4c2ec (T240/P1/T254 до API22)
ordinary-merge09655b6 (actual17 storage checkpoint) и main73425c9.
Она сохраняет enabled:false review policy и не содержит поздних ancestors
c88d947/4c99681 с runtime activation. Эта база не означает завершённый T161.
Обычный merge базы в T241 `b335c307` не меняет tree относительно bb94309.
Draft PR направляется в эту временную review base; retarget main только после
фактического merge P2/DDL16 и T161/DDL17, normal composition и exact-head CI.
Новая migration fork/rebase/cherry историй не создавались.

## Customer-only facts: согласованный T039 follow-up

Служебный `origin=proactive` — native-fault anchor без client_id, а не жалоба.
`v_cabinet_signal_facts` теперь содержит `origin IS DISTINCT FROM 'proactive'`: 
все cabinet signal cohorts/list totals/live dynamic/source/CSI выводятся из
клиентских обращений. Technical raw signals/Trace сохраняют service anchor;
`v_cabinet_incident_facts`, реальные инциденты, saved incident_economics и
affected fault не фильтруются. Это семантика customer cohorts, не auth/RBAC.
API22 descriptions уточнены до human review, поле/версия API не менялись.
DDL18 ещё не применена main: canonical/schema/mirrors нормализованы без новой
revision/миграционного fork; ORM shape110 неизменна.

Actual proof:69 scoped PG/unit green78.42s; после test-only cleanup fixture-link
четыре новых service/customer/NULL cases повторены:4passed30.31s.
Сервисный proactive/clientNULL/channelproactive не виден в customer list/count;
реальный связанный incident и saved economics неизменны, Trace200/rawsignal
сохраняются; проверяемые GET fingerprints неизменны. Money materialization
выполняется только явно при подготовке собственной fixture до readonly фазы.
Canonical origin остаётся NOT NULL: legacyNULL проверен исполнением фактической
view SQL над nullable CTE shape, без DROP NOT NULL и записиNULL в таблицу.
Новый p95 demo guard <300 входит в69target; прежние40.49/24.15ms относятся
42f2488 и не переименовываются в новый source. OwnUI5000fixture originproactive0,
её старые screenshots не выдаются за synthetic-service regression.

## PR186 exact-head CI triage и исправление isolation

CI run41439452901, headf15b02d: это новые CI failures, не прежние11локальных.
- backend shard2/job125257357127:587passed/21skip/**32setupERROR** — всеcabinet_db.
Production CorpusError корректно запретил несовместимый receipt: предыдущий
shard module test_behavior_owner::prepare меняет sim_state.seed на1, затем
cabinet_db запускал seed поверх общейDB (receiptseed42). Сообщение общее для
sha/seed/anchor, изменениеcorpusSHA не утверждается.
- backend shard1/job125257357195:572passed/**7failed** schema cases.
`lifecycle_composite_probe` оставался public после DELETErows:94вместо93,
Alembic remove_table drift, затем cascade failures после прерванногоdowngrade.
Остальные checks, включая e2e-smoke, успешны; aggregate tests правильно failed.

Test-only correction: существующий fresh-schema/upgrade код migrated_db/seeded
вынесен в один test helper rebuild_schema; cabinet module теперь явно получает
freshschema и точно5000clients перед demo seed. Production corpus guard, T017
immutable bank, productionseed/schema counts не менялись. Synthetic composite
probe удаляется вfinally **после** foreignguard/retry/purge assertions; DROP не
заменяет проверку внешней ссылки, strict93/no-drift assertions сохранены.

Точное order regression: BehaviorOwner seed1 → cabinetdemo5000 всеcases +scope
units →4populated compositeFK lifecycle cases →все9schema tests: **83passed,
110.84s**,2existing Alembic deprecation warnings. Это воспроизводит оба CI
state boundaries без ослабления проверок; exact new-head CI требуется повторно.

## Второй exact-head CI: URL fixture

PR186 f987591 / run41453475631 / job125304214225: 620 passed,21 skipped,
3 failed. Все три — `KeyError: DATABASE_URL_TEST` в async test helpers
(saved economics, automatic compliance, service anchor). CI задаёт только
DATABASE_URL; общий conftest это поддерживал, а эти helpers ошибочно читали
TEST-переменную напрямую. Предыдущие32setup/7schema failures закрыты.

Исправлен только test helper URL: три функции получают уже разрешённый
`cabinet_db` fixture, собственные environment lookups удалены. Production
handlers/DB/денежные формулы/guards не менялись. Проверены все69cabinet+scope
cases при **намеренно отсутствующем DATABASE_URL_TEST** (launcher assert),
только DATABASE_URL собственной scratch DB: **69passed90.14s**. Ruff/format
и поиск environment accesses в новых cabinet tests чистые. New-head CI
по-прежнему обязателен, результат f987 не переименовывается в success.
