# T242 — настоящий кабинет продукта

Stacked branch `codex/T-242-product-cabinet` поверх `codex/T-243-server-calculator` (T241→T243→T242).
Новый API24 producer пришёл обычным merge T243cb115a3; API/DDL вручную в UI ветке не менялись. Включён текущий main73425c9 обычной
композицией через T241; временная foundation review base описана в T241.

## Поведение

- `/cabinet` и `/cabinet/:productLine` открывают семь `data-block` из TZ24.4: scope/роль/видимость/период/run; KPI; карта/топ5/регион; лента20 и пагинированная таблица; динамика/источники; компактный actual CSI; калькулятор в Drawer. CSI скрыт для направлений без отделений и без наблюдений; блоков никогда больше7. Legacy index/marшруты не заменены.
- Только generated API22 types, actual overview/signals/roles. Ключи cache учитывают role/binding/run/period/line/filters; WS invalidation дебаунс500ms; чужой scope не используется как placeholder. `current` явно отправляется, `all` выбирается пользователем.
- Presets — представление, не auth/RBAC. Product manager без binding не получает придуманное первое направление. Strict foreign403, каталог только разрешённый; soft `all` явный. PATCH visibility сохраняет соседние settings. Compliance default existing-type OR red_word/legal_regulatory/linked misselling, explicitfalse снимает presentation preset; overview не меняет направление.
- Global PriorityStrip/NightDigest **не монтируются** на cabinet в обеих Shell. Scoped night digest внутри существующего signals-блока читает тот же cabinet/run/period/role API, без global incident/signal queries.
- Реальная геометрия РФ/центроиды, зоны из scoped threshold API, hover/focus prefetch, Enter/Space/Escape, zoom400ms, другие регионы opacity0.35, reduced motion instant. Регион показывает реальные level/routing/channel/platform; топ5 и counts берутся из overview.
- Статичная4px red-word полоса с иконкой; не более двух предложений masked summary от API; authoritative sla_due_sim vs sim_time, тихая4h метка из settings. ID/trace ссылки сохраняют run_id. Signal Drawer read-only, старый scope закрывается немедленно.
- ECharts SVG без анимации, current CSS ink/status tokens, 30 daily saved-money gaps / 12 months synthetic+partial+quality labels / platform catalog text-only. Нет fake0: неизвестные деньги/доли — `—`, known0 сохраняется.
- CSI — реальные linked responses, branch_known/wait_known и nullable branch/average; общий поток visits не приписывается направлению. Калькулятор — явное сценарное допущение по actual settings/rates, ставка направления; расчёт только GET preview→единственный dcltv.compute; anonymous coverage не превращается в0 и не запускает расчёт без ввода. Денежных writes нет.
- Local Undo8s только UI filters/preset/drawer; pathname/run/line/period инвалидируют; сохранены прежние правила остальных маршрутов. Rapid reset/stale callback проверены. X-Cx-Role добавляется shared API client только выбранному nondefault preset; explicit caller casing/header приоритетнее. Body/HITL/auth не меняются.

## Проверки и actual доказательства

Final coherent runtime source `833690` (T24119135 customer-only view18 +T2431acc686/API24); handoff81066a8 normal-merges T24372a4365/T241f987591, runtime diff0:
- full frontend **407 passed**,55files (финальный `make lint` также повторил этот набор); полный composed `make lint` green (Ruff447/mypy292, bot11/5, drift193/193), typecheck green; обе production builds (`vite build` и personal) green; i18n2019keys и generated TS без diff; tasks205 дважды без diff;
- actual production Playwright **5/5**,27.7s: ru/en × light/dark, реальные KPI/API, keyboard map/prefetch/completedopacity0.35, signal Drawer, full-viewport calculator/visible input/focus Escape, strict own/foreign403, softall, reset/Undo, mobile360 nooverflow/header≤100, fixednight/reducedmotion,7blocks и scoped digest IDs;
- все31actualcatalogcodes по одному выбраны через UI с HTTP200 и совпадением serveramount, region-prefill/servermoney, known0→server0 и unknown→noquery/`—`; palette text minimum≥4.5/control≥3 в каждой теме; infinite animations0, page errors0, page non-GET attempts0, global incidents/signals queries0, external0. Setup/restore fixture явно PATCHит только собственные settings — **не утверждается DB unchanged для всей browser фазы**;
- read-only cabinet API отдельно: финальный T24165PG/unit green,98%coverage; demo5000/2813signals,25GET каждогоscope, bank p9540.49ms/direction24.15ms,107 public/private table fingerprints unchanged, LLM/external0 и safe EXPLAIN (`T-241-demo-performance.json`). Никаких compute_incident/money writes;
-14curatedPNG просмотрены и tracked в `docs/screenshots/T-242`; exact hashes/actual guards — `T-242-browser-proof.json`.

При visual review найден и исправлен clipped fixed Drawer внутри hover-transformed
card: Drawer перемещён наружу, shared Drawer/CSS не менялись; новый unit+actual
bbox regression не допускает повторения. Снимки ждут конца fade-in, не выдают
промежуточную прозрачность за готовый экран.

## Оставшиеся gates и отдельные карточки

T241 API22/DDL18/actor_role и T243 API24/explicit-rate boundary требуют human contract/financial review; exact-head CI обязателен.
Исходный backend full gate и focused corrections/remaining phases versioned в
T241 report, не выдаются за единый финальный зелёный `make test`. Реальный GigaChat
не вызывался по заданию, его DoD proof здесь отсутствует.
T244 report всё ещё реальный guarded501, кнопка показывает server problem;
T249 полный CSI — отдельная задача, текущая компактная сводка основана на данных.
T243 serverproducer/formatter внедрены отдельным API24 пакетом; local arithmetic
удалена, fullinput/scopekey+AbortSignal и error guards не показывают чужую/старую
сумму (включая refetch error с cacheddata). Ставки передаются code, три decimal
цифры каталога не округляются до копеек до расчёта; денежный результат округляет
только server core. Ранее versioned UI00d6 был structural proof и содержал local
arithmetic gap — это не financial acceptance и не итоговый producer.
Actual GET phase35requests/31codes+known0+422:107table fingerprints unchanged,
BombLLM/external markers absent. Браузерная fixture PATCH settings выделена отдельно.
T262 canonical cabinet_red_words_report scenario14 ещё отсутствует (existing
number14 demo20_branch_queue — другой сценарий); этот сценарный DoD не подменяется
UI smoke. Формулы/premium/HITL policy не расширялись. Статус карточки in_progress до CI/review, placeholder KPI нет.

## Финальный coherent handoff

T241f987591 exactCItest-isolationfix обычнымmerge включён черезT24372a4365.
Новыйhead меняет толькоtests/docs относительно проверенногоruntime833690;
`git diff --quiet 833690 -- backend/app contracts frontend/src`=0. Никакого
позднегоT039/T161runtimeWIP. API24 иcustomer-view18 присутствуют вместе, ownUI
схема18 пере-примененаидемпотентно, previewперезапущен доfinal5caseproof.
Вbaseline originproactive0; negative service/customer/nullable projection
доказаны отдельнымиT24169+4PG, coherent API24/service18target18green38.78s.
ПослеCIfixturefix14calculatorunit/PGgreen12.34s. RootPR186f15CI реальноfailed:
32cabinetsetuperrors из-за sharedseed1/receipt42 и7schemafailures от leaked
syntheticprobe; исправленыf987,83exact-orderregressionsgreen110.84s, новыйCIpending.
Historical full gate не выдаётся за exactfinalCI.

Последнийproduction5caseproof27.7s включаетevery31selectorcode→HTTPserveramount
иactualemptyregion0→prefill0→server0. Anonymousregionunknownне подменён0;
positiveidentifiedprefill проверенunit/actualPGcoveragefixture.14PNG сохранены
изэтогоcoherent source.35GET/107fp повтореныпослеbrowserfixtureфазы, unchanged,
LLM/external0. Дваruntimeфикса приQA (card-transformDrawer/duplicate localarith)
исправлены и защищены регрессиями; всеAPI/money approvals ещёpendinghumanreview.
