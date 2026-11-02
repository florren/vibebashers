# T-255 — реальный «Обзор», локальный implementation checkpoint

## Поведение и границы

Реализованы ровно девять блоков ТЗ26.4: шесть KPI, CX/проекция, микс каналов,24часовой поток, native decision-chain выбранного agent run, customer лента, первые3pending HITL без действий решения, давление/exact saved money, сворачиваемый компендий сохранённых summaries с source/mode. Значения берутся из API29 и существующих typed endpoints. Формула CX остаётся в producer T256; денежные формулы/проводки/HITL policy не изменены. Exact Decimal строка сохранённой суммы форматируется существующим helper без Number. Unknown не превращается в0; coverage, источники/окна и неполная выборка ленты показаны явно. Светофор обозначает подключение event stream, не придуманную «норму» банка.

Проекция использует фактический integer negativity0..100 и стабильный ID angle. Unknown не рисуется как нулевой негатив; service proactive и записи вне окна исключаются. География не подразумевается. Шаги/summary masked; входящий raw текст/contacts не попадает в projection cache. Чипы строго следуют26.5: tone/flag sarcasm, high, negativity≥67, без новых enums.

Current разрешается через API29 в точный numeric run для дочерних запросов и ссылок. current_missing отключает ссылки/queries; пустой/Unicode/overflow URL scope не превращается в all при qs(). На explicit-run Workspace/Engine/Economics сначала серверная scope validation, затем только scoped children. Engine проверяет принадлежность выбранного AR через существующий keyset list до detail/chain/LogPanel; повтор cursor — явная ошибка. Legacy без параметра сохраняет прежний all/default flow. В обоих Shell на Overview/explicit-run URL не монтируются globalPriorityStrip/NightDigest; ночью scoped high digest внутри существующего feed блока, девятый блок не добавляется. WS sim.tick/signals/agent инвалидируют новые readonly metrics через существующий throttle250ms, не запускают legacy global economics на каждом tick.

Calm/control_room содержат9блоков; анимации графиков отключены, focus/keyboard и таблицы-альтернативы доступны. Brand/ops, ru/en,light/dark и360px проверены. Russian native saved summary в EN сохраняет исходный язык с явной подписью.

## Проверки точного UI source

`make lint` green: frontend470tests/65files (15.02s), Ruff505formatted, mypy311, bot12formatted/5mypy, OpenAPI194/194. Обе production builds main/personal green. Playwright8/8 actual production cases (без retries/подмены API): API↔UI KPI/CX/exact money,9блоков, palette text≥4.5/control≥3, reduced motion, отсутствие infinite animation, desktop1440 иmobile360, реальная keyboard SVG→Trace HTTP200. 24PNG (8×top/bottom/mobile) в `docs/screenshots/T-255/`; mobile показывает весь блок при viewport360. Узкий ResizeObserver reflow проверяется expect.poll≤1px; порог не увеличен, исходный transient overflow counterexample сохранён в /tmp evidence.

Отдельный actual read-only walkthrough6маршрутов (Overview, Workspace dashboard/signals/HITL, Economics, Engine ownAR) сохранил hashes/counts ВСЕХ111таблиц public/private:0changed,0nonGETattempts,0external,0legacyglobalKPI/economicsrequests,0pageerrors. Settings fixture PATCH/import выполнены до/после fingerprint фазы и не выдаются за read-only. Seed/startup backfill/native Mock graph также завершены ДО readonly phase. Native fixture run3:3сигнала, реальные completed/awaiting_human/deferred graph outcomes, только mock model; никакой API подмены.

Machine proof `T-255-overview-proof.json` содержит per-file sourceSHA256,8browser samples/palette,24PNG count и safe111table count/hash fingerprints (без rawrows). Исторический full backend2770passed/24skip относится к producer runtime1968631; новый UI fullfrontend470 green. Новый composed backend fullgreen здесь не заявляется.

## Остаточные зависимости и rollback

До публикации нужны ordinary composition API29 defensive409+root T041 stale-controller fence и native probes/p95 producer; root T249 explicit-run readonly Journey consumer (в этом checkpoint проверены scoped href, сам Journey не изменён), parentreview/CI точного composed head. T257 не включена. Карточка in_progress, общий DoD не отмечен закрытым. Откат: revert scoped T255 commit; никакие DB/schema migrations/сохранённые деньги не меняются. API29 producer откатывается отдельно своим PR.

## Окончательная composed проверка

Source `1c9c365` включает ordinary API29/T041c47 + clean root Journey/CSI/API28/receipts27 stack. При объединении двух real routes убраны только уже неиспользуемые PendingScreen/t вApp; обоим словарям сохранён lossless union. Backend/app tree побайтно совпадает с parent API29 PR201 head1d248; metadata/DTO/types не откатывают API27/28.

Final make lint485frontend/69files,550format/323mypy,bot12/5,drift196/196 green; обе production builds green. Actual0020/demo5000 scoped102unit/PG/HTTP/control/shutdown tests green60.43s. Первый101/1fixtureF не был runtime дефектом: T039 правильно запрещает proactive origin черезapi; focused1c9 создаёт internal service fixture через существующую normalizer authority fault_monitor/system_logs, customer asserts сохранены.

Final8/8actual production browser9.1s,24PNG в том же curated каталоге обновлены с этого source (прежние остаются в Git192267b). Новый read-only8route walkthrough включает explicit-run JourneyFollow/Replay, в дополнение к Overview/Workspace dashboard/signals/HITL/Economics/Engine.114public/private table hashes unchanged;0nonGETattempts/0external/0legacyglobalmoneyKPI/0pageerrors. Schema20/newseed/nativeMockrun2 и startup abs_backfill завершены ДОfingerprint; настройки fixture PATCH/import вне read-only фазы. Native recorded latency0ms допускается, если действительно записан finished step: это измеренный Mock execution, не неизвестное время.

Machine proof обновлён на finalsource; старый192/6f proof доступен в истории Git. Публикация остаётся через parent draft/точный CI; нового полного backend green здесь не заявлено. T257 отдельная ветка и в этот consumer diff не включена.

Публикационная ordinary composition: parent API29 PR201 head1d248 → merge336bb1a. Перед merge собственный preview остановлен. `git diff 7efb753..336bb1a -- backend/app frontend/src contracts/api/openapi.yaml` пуст: все485/102/8/114evidence относятся к тем же application bytes; новые parent изменения — docs/test fixtures. Генератор дважды после merge идемпотентен206cards. Наследованный privacy test оставлен byte-identical parent (различался только docstring), без изменений assertions и без лишнего backend delta в UI PR. Новых broad прогонов для неизменённых application sources не делалось; exact CI обязателен.
