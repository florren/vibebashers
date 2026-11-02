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
