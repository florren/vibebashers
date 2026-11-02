# T243 — единый денежный producer, API1.5.24

Human review требуется для additive API/денежной границы по AGENTS6.4/7;
согласование прошлых денежных PR не подменяет review этого diff.
Stacked от clean T241f15b02d, без локальной формулы T242. API23 зарезервирован
T122 и не входит в этот parent; при будущей композиции сохранить оба diff,
версия24 старше23. DDL не менялась, новые ставки/числа/дефолты не добавлены.

## Конкретная граница

Существующий `GET /api/metrics/economics/preview` принимает optional `rate_code`
(1..120символов), lookup только в actual `dcltv.load_settings().rates`. Unknown422,
сочетание с любым явно переданным product/system (даже пустым)422 доDB.
Без rate_code прежний pick_rate/product/system/fallback без изменения.
Segment/shares/known0/premium/retention0/open остаются прежними. Явная ставка
создаёт существующий `dcltv.Rate`, единственная формула и ROUND_HALF_UP —
`app/economics/dcltv.py::compute`. Нет вызовов compute_incident/recompute,
суммирование не записывает incident_economics, нет HITL/платежей/retention policy.

Выбор из каталога — явное сценарное допущение, не переписывание ставки инцидента.
Сегмент absent означает прежнюю premium_addon0; explicit premium segment
сохраняет прежнюю доплату. Все существующие коды доступны, включая
premium_service как явно выбранную базу: новая скрытая специальная трактовка
кода не вводится. Сценарный potential не становится сохранённым ущербом.

Подтверждённый count drift: карточка/ТЗ говорят30, но canonical
`data/dcltv_rates.csv` и seeded DB содержат **31** запись (включая notifications).
Проверяется exactCSV↔DBset и каждый existing31 code, entry не скрываются и
новые значения не придумываются. Родитель подтвердил этот superset.

## Consumer boundary и формат

Shared `useEconomicsPreview` принимает generated query/IncidentEconomics DTO:
fullinput/scope cache key, AbortSignal, null disables query, known0 explicit,
нет placeholder старой суммы и нет fallback при error. Интеграция T242 должна
полностью убрать local multiplication, брать готовый server potential/множители.

`formatCompactRub` только форматирует готовую сумму: null/nonfinite — `—`,
0/−0 —0, целые тысячи не сокращаются, миллионы/миллиарды ru/en, Unicode minus.
Округлённые1000млн поднимаются до1млрд; финансовая исходная сумма не меняется.

## Проверки

-14 targeted backend tests green15.04s: legacy631.52 и known0, explicit round,
ambiguous/querybounds/NaN/Infinity/unknown422, actual31rates и совпадение
с сохранённой записью настоящего compute_incident fixture;
-HTTP фаза после явной fixture подготовки: все public fingerprints неизменны,
BombLLM0, запрещённые materialization producer0. Fixture money write не
приписывается GET. Нет внешних каналов/LLM/production;
-новые backend executable lines7/7=100% относительноf15b02d, артефакт
`T-243-producer-coverage.json`. Whole metrics.py43% не выдается за newcodecoverage;
-shared frontend18 tests:15format boundaries +3query unknown/known0/race/abort/error;
-full frontend372passed, обеproductionbuilds/typecheck/lint green;
-первый make lint:447Ruff/292mypy, bot11/5, drift193/193; generatedTS/45schemas/163paths
и tasks205 проверены; 422Problem response явно задокументирован; final generation выполняется последовательно после unit;
-первый full unit1757passed/18skip +2old test-onlyGET501 failures после собственного
productionbuild: SPAcatchall был раньше test-appended route. Production handlers
не менялись: focused fixture ставит объявленный тестовый GET передcatchall и
проверяет deterministic SPA/noSPA,9passed3.74s, всеGET/501/problem/card/instance
assertions сохранены. Финальный полный составной rerun **1761 passed /18 skipped,56.87s**.

## Статус

Это concrete producer/contract/shared-consumer пакет, не полная UI приёмкаT243.
Карточка in_progress до normalmergeT243→T242, actualserver calculator/map/31rates
proof, ru/en×themes/screenshots и CI/human financial review двух PR.
Никаких утверждений о realGiga DoD или полном backend integration rerun.
