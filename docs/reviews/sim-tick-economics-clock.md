# Tick clock и наблюдение native service economics

## Дефект и граница изменения

При native Team.take внутри одного tick память Simulator уже находилась в T1,
а sim_state в той же транзакции оставалась в T0. Положительный lineage/cohort
control проходил в T0; последующий штатный take падал с
`fault_monitor economics: проверьте native producer lineage и часы своего запуска`.
При росте реального cohort возникал второй отказ: cached mass_impact отставал
от actual same-run failed operations.

Исправление записывает T1 до эффектов tick внутри прежней общей транзакции.
Независимый MVCC reader не видит T1 до commit; отказ откатывает time/RNG/stats/events.
Плановые team action и SLA timestamps сохраняются. Расчёт экономики наблюдает
состояние собственного run на tick time, а не на более раннем плановом action time.
Для delayed actor используется актуальный clock того же run; чужие часы не берутся.

Native service cache обновляется только из проверенного lineage и реальных
same-run failed operations. Заниженный counter может вырасти до actual cohort;
завышенный counter вызывает прежний явный отказ, без автоматического уменьшения.
Прямой dcltv consumer продолжает требовать точное соответствие cache и cohort.
Future observation, future operation и ложный lineage не становятся допустимыми.

Формула dcltv.compute_incident, ставки, retention coefficients, суммы подарков,
проводки, лимиты и HITL не меняются. API/DDL/event schema не меняются.
История и production DB не переписываются; production stack не перезапускается.
Автоматический gift timestamp — отдельный согласованный PR #213.

## Проверки

- RED: native graph + canonical fault/failed operation + настоящий Team.take
  воспроизвели отказ часов после положительного control.
- RED: увеличение cohort между планированием и take воспроизвело отказ counter.
- GREEN: 16 PG cases — boundary/rollback и существующие отрицательные economics
  guards (до последнего усиления assertion сохранения corrupt counter).
- Full unit2178passed/19skipped (штатные skips),64.78s.
- Native extended regression:47passed; один новый atomic test имел ошибочный
  дополнительный assertion (`NameError`), исправлен без изменения продукта.
- Повтор финального boundary/negative economics + SLA/Team:41passed,104.07s;
  atomic MVCC/rollback, corrupt counter и future guards зелёные.
- Team recovery/RNG/SIGKILL/dump clone, proactive runtime120/90/30 и delayed
  recovery/effect-time входят в47успешных extended cases.
- Измерение исполнения добавленных production statements штатным sys.settrace:
 48/53 (90.57%); denominator — AST statement starts в добавленном diff. Это не
  заявление о100% полном покрытии проекта или semantic correctness ответов LLM.
- Terminal automatic gift + manual tasks API:2PGpassed,14.41s.
- contracts:48schemas/167OpenAPI paths; owners --allow-cross passed.
- gen_tasks запущен дважды: статусы/acceptance всей карточки не повышались.
- Ruff и mypy strict: 328 source files, без ошибок.

## Review / откат

Требуется отдельное подтверждение по AGENTS.md §5.1: «всё, что касается денег и HITL».
Ранее одобренные gift timestamps не покрывают этот расчётный scope.
Откат кода возвращает прежний clock/cached-cohort отказ; сохранённые истории не
редактируются. При отказе tick вся его транзакция откатывается; автоматического
исправления завышенного counter нет. Для отката остановить собственный тестовый
runtime; действующий production runtime этим пакетом не менялся.
