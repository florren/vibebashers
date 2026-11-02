# T-252 — циркадный движок и доказательства

## Реализация

Ветка `codex/T-252-circadian`, база `1df0024`, ordinary merge main `d2a4026`/`dfbf47a` и одобренной dependency PR167 `42b6d3e`. В собственном diff T-252 относительно одобренной dependency не меняются backend, SQL, миграции, OpenAPI или npm-зависимости. T-253/T-254 не включены.

`frontend/src/shared/theming/circadian.ts` — один исходник для runtime и inline bootstrap. Vite использует свой публичный `transformWithEsbuild` для встраивания classic IIFE до первого paint в `index.html` и `personal.html`; формулы не копируются и generated JS вручную не редактируется. Ручные light/dark, auto и плотность сохраняют прежние интерфейсы.

Источники: `sim` по умолчанию — только ISO-час симулятора и его дата (GET state/WS `sim.tick`, последний валидный час кешируется); `real` — часы устройства с проверкой раз в секунду; `fixed` — выбранная фаза. Ручной mode/fixed приоритетнее автоматических часов и сохраняется. Публичные страницы используют локальный `ThemeClock` без операторских API/WS.

Сезонные восход/закат рассчитываются офлайн по [NOAA General Solar Position Calculations](https://gml.noaa.gov/grad/solcalc/solareqns.PDF): equation of time, declination, zenith 90.833°. Високосность учитывается. Координаты по умолчанию Москва (55.7558, 37.6173). Солнечная дата определяется через долготу, без зависимости от timezone/DST устройства. Фазы делят светлую/тёмную часть суток; при 12-часовом дне опорные границы — 05/07/11/16/19/21. Для polar day явно используется `noon`, для polar night — `night`; искусственные восходы не придумываются.

Geolocation вызывается в единственной точке после явного нажатия кнопки с объяснением цели. Координаты/факт согласия остаются в localStorage, не уходят в settings/API/логи; можно забыть местоположение и вернуться к Москве. Отказ не затирает прежнее местоположение. Координаты используются в локальном солнечном расчёте; Header рабочих часов всегда Europe/Moscow по ТЗ 4.1.

Общий `fmtSim` с прежней UTC-семантикой сохранён. Только три Header clock используют новый явный `fmtSimMoscow` с прежними Header patterns, ru/en и Europe/Moscow, без сдвига от timezone устройства.

## Settings и совместимость

Существующий generic `/api/settings` допускает additional properties, новый контракт не нужен. PATCH имеет вид `{ui: {circadian: {source, fixed_phase}}}`. Backend делает shallow merge ключей внутри `ui`, поэтому `lang`, theme_pack, mode, density и другие соседние ключи сохраняются; собственный объект circadian записывается целиком из двух валидированных полей. Coordinates не входят в этот объект.

Сохранены сериализация PATCH, pending queue/offline retry, приоритет локального изменения перед запоздалым GET и защита даже после более раннего ACK PATCH. JSON-объект circadian сохраняется в localStorage как JSON, остальные прежние поля как строки.

## Переход и доступность

Каждый автоматический переход — requestAnimationFrame на 8000 ms. Палитра поверхностей интерполируется непрерывно; при смене светлой/тёмной полярности поверхности сходятся, чтобы общий foreground оставался читаемым. Непрерывная интерполяция текста через серый нарушила бы WCAG: необходимая смена полярности текста дискретна, а текст/status/focus на каждом кадре проходит contrast guard. Статусные оттенки сдвигаются к читаемому foreground; цвет не является единственным носителем смысла.

Сторонние CSS transitions контролов отключены на время guarded-перехода: иначе foreground мог бы отставать от проверенной поверхности. Новый tick той же фазы не обрывает переход; новый переход начинается от текущей палитры. Ручной выбор и reduced motion отменяют анимацию, media preference отслеживается также во время перехода.

В `night` отображаются неподвижные звёзды/луна opacity 0.06 с `aria-hidden` и pointer-events:none, а также inline «Ночной дайджест». Он читает существующий GET signals `criticality=high, run_id=current, limit=10`, обновляется существующими WS invalidations и polling. Показываются только public_id-ссылки, без raw text/контактов; наличие следующей страницы явно сообщается. Панель не является popup. Глобального toast-сервиса в исходной реализации нет; существующие живые алерты `/manager` и `/compliance` не изменяются, слой/digest там не включаются.

## Проверено: версии и источники разделены

### Полный замороженный checkpoint c71a918

`make lint && make test` на собственной scratch-БД: backend: 1486 passed / 22 skipped (unit: 1168 / 18 skipped, integration: 245 / 2 skipped, scenarios: 42 / 2 skipped, compliance: 31), frontend: 286 passed. Source/tests во время полного прогона не менялись. Это исторический full-result c71, а не подмена проверки последующих frontend изменений.

### Окончательный source 18ad9fd

После bounded frontend fixes выполнены обычные merge main dfbf47a и user-approved PR167 dependency42b6d3e. Собственных backend/DDL/contract изменений в T252 нет; prefix 9 взят из отдельного одобренного PR.

- `make lint`: весь frontend: 292/292, ESLint/typecheck; Ruff: 365 files, mypy: 257 modules, OpenAPI drift: 192/192 — зелёные. Прежнее предупреждение react-refresh DemoMenu этой задачей не добавлено.
- Обе production сборки operator/personal проходят.
- Contracts45schemas/162paths, i18n: 1750keys, TS generation и205 task headers — идемпотентны.
- 36 pack×mode×phase cases читают реальные CSS токены; circadian faint также проверяется. Все 72 направленных перехода обоих пакетов×101 samples проверяют text/status≥4.5, control/focus≥3, button text≥4.5; decorative line/brand интерполируются.
- Seasonal/leap/polar, sim/real/fixed, ручной приоритет, consent/denial/forget, settings race/offline, digest PII/run-cache/exceptions. Годовой sweep lat±60..89, lon−179/0/179 проверяет более200000 границ; четыре midnight edge cases закреплены отдельной регрессией.
- Bootstrap и runtime одинаково обрабатывают повреждённый mode и валидный legacy fallback. Late GET settings с идентичными prefs сохраняет текущий WS-переход; контролы при manual/reduced motion применяют цвета сразу, без запаздывающих CSS transitions.
- NightDigest scope key учитывает real runs events и live current_run_id; запоздалый ответ предыдущего scope не показывается. В кеше только id/public_id, без полного Signal DTO. Ссылка ведёт в существующее рабочее место `/`.

### Production browser: synthetic transport

`frontend/e2e/circadian.spec.ts`:5/5 passed, 14.8 s на final source 18. Покрытие:2packs×6phases×ru/en; manualinstant/reload/no-flash; controlled late-settings GET во время8s; reduced motion; realclock/explicit geo; manager/compliance exceptions;390×844;3 browser timezones UTC/New_York/Auckland×ru/en×ноябрь/US DST boundary8марта. Общий UTC fmtSim test сохранён, Header06Z→09MSK проверен отдельно.

473 samples реально отрисованных кадров за 7906 ms: min text 4.5000129458, min control 3.0000002153. Source интерполяции использует 8000 ms; sampled window начинается после первого наблюдаемого кадра. Ошибок/внешних запросов: 0, geo только по явному тестовому клику.

### Production browser: настоящий API/WS

`frontend/e2e/circadian-actual-proof.mjs`, localhost18153, source 18ad9fd, отдельная cx_circadian_revision, fresh seed200/schema 0010/baseline1/completed/06Z. Actors до seed 0; новый process строго после seed. API/WS настоящие, route mocks нет; runtime chain/roles толькоMock, внешний socket/DNS запрещён wrapper. Browser timezone America/New_York.

1. APIset_speed 60 и явный preparation jump_to ставят часы перед seasonal morning/noon.
2. Настоящий APIstart:08:29:36.337Z→08:38:06.337Z;9 естественных running sim.tick, speed 60. UI morning→noon наблюдался через 108.7 ms после start, затем завершился штатный 8 s переход.
3. Отдельные APIpause и **явный jump_to17:30Z** дают night и Header20:30. Это не естественная ночь за9тиков и не fixed-источник. В полном сценарии21 sim.tick: 3 prepare + 9 natural + 9 night chunks.
4. Header сопоставлен независимому Intl Europe/Moscow: initial06Z→09:00, после pause08:38Z→11:38, night17:30Z→20:30. Errors/external/geo по умолчанию0. Ночная панель показывает настоящие public_id текущего scratch-прогона.

4 actual API PNG просмотрены и tracked в `docs/screenshots/T-252/`; там же `proof-summary.json`. Полные JSON и логи final source — `/tmp/vibebashers-t252-actual-prefix9/`, `prefix9-browser.log`, `prefix9-lint.log`, `prefix9-meta.log`, `prefix9-browser-regression.log`.

## Зависимость и выявленная отдельная неисправность

На историческом874, где error-code prefix ещё ограничен6, тот же night jump дал 409: ANTIFRAUD-FALSE-BLOCK не соответствовал regex. Это уже одобренная правка PR167 prefix 9; она обычным merge добавлена как dependency, после чего полный actual сценарий проходит. T252 не обходил валидацию и не менял backend. Исторический automatic9tick proof874 и safe409 metadata сохранены отдельно, c71 также не выдаётся за новый source.

Повтор после обычного backend exception выявлял повреждённый World/RNG cache и operations_fault_fk500. Родитель подтвердил общий rollback gap и передал отдельному P1 producer; T252 его не исправляет. В final prefix 9 actual сценарии exception не возникает и обходов/внутренних monkeypatch World нет.

## Воспроизведение и оставшиеся gates

Стандартные команды: `cd frontend && npm test -- --run`, `npm run build`; production preview localhost18152; `E2E_BASE_URL=http://127.0.0.1:18152 npx playwright test e2e/circadian.spec.ts --project=settings --no-deps`.

Для actual proof сначала остановить акторов **только выделенной scratch-БД**; существующий `test_coverage.py::test_seed_is_idempotent` пересоздаёт её public и готовит200syntheticclients. Затем новый backend с APP_ENVdev, LLM_PROVIDERmock, LLM_CHAINmock, FRONTEND_DIST из своей сборки, host127.0.0.1/port18153; `cd frontend && node e2e/circadian-actual-proof.mjs`. Локально использовался Node26 и PLAYWRIGHT_BROWSERS_PATH=/tmp/cx-playwright-142-node22; NODE_OPTIONS=--no-experimental-webstorage. Никакие production БД не используются.

Реальный GigaChat в этом UI-пакете не вызывается по явному ограничению родительского задания; общий live DoD составного стенда остаётся у родителя. Dependency PR167 учтена; до exact-head CI/review и merge T252 карточка остаётся in_progress. Push/PR выполняет родительский агент.

Ownership check относительно dependency42b6d3e проходит с user-authorized `--allow-cross`: L1 review/screenshots и L5 browser proofs перечисляются в PR, нужен cross-layer label. Собственный diff относительно dependency не содержит backend/contract файлов.
