# T-255 — публикационный checkpoint «Обзор»

Реализованы ровно девять блоков ТЗ26.4: шесть KPI, CX/проекция, микс каналов,24часовой поток, native decision-chain выбранного AR, customer лента, первые3pending HITL без действий решения, давление/exact saved money, сворачиваемый компендий сохранённых summaries с mode/source. Значения из API29 и существующих typed endpoints. Денежные формулы/проводки/HITL policy не меняются; exact Decimal форматируется существующим helper без Number. Unknown не превращается в0; coverage/окна/пределы выборки явные. Индикатор означает подключение event stream, не придуманную «норму» банка.

Проекция использует recorded integer negativity0..100 и стабильный ID angle, подпись «не география». Unknown не рисуется как нулевой негатив; service proactive и записи вне окна исключены. Raw text/contacts не сохраняются в projection cache; шаги/summary masked. Чипы строго по26.5: tone/flag sarcasm, high, negativity≥67, без новых enums.

Current разрешается сервером в точный numeric run для children/links. current_missing отключает ссылки/queries; пустой/Unicode/overflow scope не превращается в all через qs(). Explicit-run Workspace/Engine/Economics сначала валидируют scope, затем монтируют только scoped children. Engine проверяет membership AR через существующий keyset list до detail/chain/LogPanel; повтор cursor — явная ошибка. Legacy без параметра сохраняет прежний flow. Оба Shell не монтируют globalPriorityStrip/NightDigest в Overview/explicit-run context; scoped high digest ночью находится внутри существующего feed блока. WS sim.tick/signals/agent инвалидируют новые readonly metrics через throttle250ms, без legacy global economics на каждом tick. API29 обзор не preset-filtered: consumer сохраняет существующую политику, новый RBAC не вводится.

Calm/control_room содержат9блоков; графики без анимаций, keyboard/focus и таблицы-альтернативы доступны. Russian native summary в EN сохраняет исходный язык с явной подписью.

## Обычная композиция и источник проверки

Proven application source `1c9c365` включает API29/T041c47, clean root Journey и CSI API28/receipts DDL19 stack, actual schema0020. При объединении двух real routes удалены только неиспользуемые PendingScreen/t вApp; обоим словарям сохранён lossless union. Metadata/DTO/types сохраняют API28/29. Parent API29 PR201 head1d248 включён ordinary merge336bb1a после остановки ownpreview. Между proven1c9 и publication55c application sources не изменились. Exact tree/blob identities — `T-255-identity-manifest.json`; backend/app и inherited target tests также идентичны parent201. Privacy test оставлен byte-identical parent, assertions не менялись; лишнего backend/contract delta в UI PR нет.

## Проверки final application source

- Make lint green:485frontend/69files,550format/323mypy,bot12/5,drift196/196; обе production builds main/personal green.
- 102адресных tests (66unit+36integration, включая actual PG/HTTP/control) green60.43s на actual0020. Initial101/1fixtureF: T039 правильно запретил service origin черезapi. Focused1c9 использует существующую internal normalizer authority fault_monitor/system_logs, все customer/window/N/C/R assertions сохранены.
- 8/8actual production browser9.1s: brand/ops×ru/en×light/dark, desktop1440/mobile360, reducedmotion, API↔KPI/CX/exact money,9блоков, contrast text≥4.5/control≥3, отсутствие infinite animation, keyboard SVG→actual TraceHTTP200.24curatedPNG — `docs/screenshots/T-255/`.
- Отдельный8route GETwalk включает Overview, Workspace dashboard/signals/HITL, Economics, Engine ownAR и explicit-run JourneyFollow/Replay:114public/private table hashes unchanged,0nonGETattempts/0external/0legacyglobalmoneyKPI/0pageerrors.

Demo5000 seed, nativeMockrun2 и startup abs_backfill завершены ДОfingerprint; настройки fixture PATCH/import вне readonly фазы. Native recorded0ms допускается при реально recorded finished step: это измеренный Mock execution, не неизвестное время. Machine evidence/source hashes/raw counts — `T-255-overview-proof.json`. Gen2 после parent merge идемпотентен206cards. Historical192/6f proof (470frontend/111hashes) сохранён в Git; полный backend2770/24skip относится к runtime1968631, новым полным composed прогоном не называется.

## Оставшиеся gates и rollback

API29/T041/Journey composition и native producer probes/p95 уже включены и проверены. До merge остаются parentreview, exact-head CI и согласованное завершение parent PR201 dependency chain; карточка in_progress, общий DoD не закрыт. T257 отдельная ветка и в этот diff не входит. Откат: revert T255 consumer вместе с зависимыми routes при необходимости; DB/schema migrations/сохранённые деньги этим UI не меняются, API29 producer откатывается отдельным PR.
