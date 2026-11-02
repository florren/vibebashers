# T-041 + T-040: проверенная композиция recovery и maintenance

Кандидат продолжает прерванный проход из PostgreSQL checkpoint в том же AR/run_id,
с прежними sim_time/RNG и без повторной проводки. Обычный startup допускает
recovery только после durable maintenance gate; Resume разрешён для текущего
paused/interrupted, stopped/completed остаются terminal409. Graceful stop сначала
приостанавливает симуляцию, затем ожидает завершение/rollback принадлежащих
сервису tasks и закрывает соединения.

## Границы runtime

База — T-0415758e2d и обычный merge T-0402a88a68; итоговая backend source revision
7b8b6b0, tree cf29ea76fd7b068f34c02a7c25da1ec8a2c882bd. Последующий UI-only
097c5d8 имеет тот же backend tree. Source основного checkout T-041 не изменялся.

Четыре recovery entrypoint получают writer lease. Оба recovery child tasks
резервируются через spawn_writer до первого шага; drain видит их даже после
возврата вызвавшего HTTP/startup task. before/afterResume callbacks сохранены.
Начальный startup ожидает _recover перед start(recover=False); после baseline
restore свежий service использует default recover=True и ждёт открытия epoch.

Automatic recovery ограничен started_at < service.started_at: fresh AR,
принадлежащие уже работающим tasks сервиса, не сбрасываются и не захватываются
повторно. Explicit Resume по-прежнему проверяет все реальные незавершённые AR.
Формальный T-273 AUTOMATIC_EXCLUDED_SQL применяется к marking/validation/recovery:
legacy mock polling и baseline seed history не превращаются в новые запросы.
Настоящий legacy AR без checkpoint получает прежний явный отказ до эффектов.
Paused/interrupted не пробуждают timers автоматически; явный Resume сохраняет
проверку checkpoint и пересчитывает scoped timers.

Старые direct recovery tests теперь дожидаются зарегистрированных async jobs;
HITL decision/outcome/escalation и followup fired assertions сохранены. Fixture
HITL явно представляет current running live-run. Старый stopped-demo Resume
заменён контрактным409 с проверкой отсутствия эффектов и явным стартом нового
сценария; это соответствует карточке T-041. Schema tests сверяют актуальный
Alembic head, сохраняя84 public tables, audit evidence, повторный upgrade и
rollback assertions. Новые checkpoint tables остаются в schema langgraph.

## Forward contract и интерфейс

OpenAPI1.5.17 добавляет только optional AgentRunBrief.status и nullable
interrupted_at (Detail наследует их). Existing outcome остаётся бизнес-исходом;
HITL/финансовые условия его использования не меняются. Поля выбираются реальными
SQL producers list/detail и nested SignalDetail, TS regenerated штатным script.
Пути и ограничения T-0675000/20RPM/429, T-091run scope и T-108 сохранены.

Общий presentation helper понимает новый status и старые ответы без поля.
Engine, SignalDrawer, LogPanel и Journey отображают interrupted; current node
статичен, без running pulse. Header предлагает Resume для paused/interrupted.
TraceResponse.subject.status уже допускает free string и читает DB status;
для agent_run карточка локализует его ru/en. Другие subject kinds не изменены.
Journey.stage.status enum не расширялся: позиция бизнес-этапа не подменяется
статусом исполнения AR. Новых Trace/Journey DTO полей нет.

## Проверки

Backend full freeze7b8b6b0:1261 passed,24 skipped. Четыре отдельных checkout и
PostgreSQL16 DB; aggregate проверил общий revision, collection/nodeids и точное
объединение выполненных testcase без потерь. Standalone unit924passed18skip.

Целевые PG проверки: compatibility/scope50passed (включая paused/interrupted,
fresh/legacy/history), первоначальная композиция38passed; actual API8passed с
list/detail/nested/Trace interrupted→completed того же AR и прежними refund1,
normalization1/token assertions. SIGKILL собственного mock production-lifespan
процесса, два restart и gracefulpause проверены; рабочие контейнеры не убивались.

Frontend final097c5d8:167passed, lint/typecheck зелёные. Real image source097c5d8,
новый isolated cx-ci project и свежие pgdata/maintenance_control volumes:
75Playwrightpassed2.5min, включая4 ru/en light/dark Graph+Trace interrupted
projection cases, static node, Resume и отсутствие browser mutations. Это
GET-mocked presentation fixtures на настоящем built image; реальная DB/API
семантика отдельно подтверждена PostgreSQL тестом. Helper cleanup exit0,
primary/latest/рабочие volumes не изменялись.

Path-filter stdlibtrace:138passed342.19s; changed executable относительно5758 —
844/968=87.19%. Фильтр по абсолютному co_filename исключает basename-cache
ошибку стандартного ignoredirs. Raw counts сохранены; при postprocessing
исправлен cwd git diff, source line0 CPython исключён как несуществующая строка.
Control и opaque guards100%; coordinator≈93%, DBlease≈92%, baseline≈87%.
Per-file missing lines сохранены в машинном отчёте; покрытие не означает, что
все ветви каждого старого модуля исполнены.

Ruff/format355files, mypy253files, contracts44schemas/161paths,
OpenAPI191/191, licenses548distributions, i18n1616keys и fresh generatedTS green.
Новых зависимостей этой композиции нет (LangGraph dependencies принадлежат
базовому T-041 и проверены inventory gate).

## Скриншоты

[Graph RU light](../screenshots/T-041-interrupted/interrupted-ru-light.png),
[RU dark](../screenshots/T-041-interrupted/interrupted-ru-dark.png),
[EN light](../screenshots/T-041-interrupted/interrupted-en-light.png),
[EN dark](../screenshots/T-041-interrupted/interrupted-en-dark.png).

[Trace RU light](../screenshots/T-041-interrupted/trace-interrupted-ru-light.png),
[RU dark](../screenshots/T-041-interrupted/trace-interrupted-ru-dark.png),
[EN light](../screenshots/T-041-interrupted/trace-interrupted-en-light.png),
[EN dark](../screenshots/T-041-interrupted/trace-interrupted-en-dark.png).

## Review и ограничения

[Машинные результаты](T-041-maintenance-compose-proof.json),
[maintenance recovery/rollback](T-040-maintenance-boundary.md),
[базовый durable contract/rollback](T-041-durable-recovery.md).

До merge нужно подтверждение человека по AGENTS.md §5: «изменение контрактов,
всё, что касается денег и HITL». Это optional API1.5.17, миграция0012/ownership
и атомарность node effects+checkpoint; формулы, ставки, лимиты и политики не
менялись. Maintenance предполагает один main process; arbitrary admin SQL и
concurrent destructive CLI seed/main не объявляются безопасными. Shared marker
не имеет TTL и не удаляется для обхода recovery.

Проверки относятся к указанной composed базе. Последующая интеграция SDK/P1 и
новых canonical credential columns требует отдельного compositional CI и
обновления fingerprint; она не включена в приведённые цифры. Общий DoD не
закрыт до human review и required CI/merge. Production/real LLM/Telegram не
использовались, push/PR/merge в main этим кандидатом не выполнялись.
