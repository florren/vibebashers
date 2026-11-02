# T-252 — циркадный движок и доказательства

## Реализация

Ветка `codex/T-252-circadian`, база `1df0024`, ordinary merge main `d2a4026` (T-234). Backend, SQL, миграции, OpenAPI и зависимости не изменяются. T-253/T-254 не включены.

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

## Проверено: источники доказательств разделены

### Unit и статические проверки

- 36 существующих pack × mode × phase contrast cases теперь читают также настоящие фазовые CSS-токены.
- 72 направленных перехода (оба пакета, все пары 6 фаз) × 101 samples: text/status ≥4.5, focus/control ≥3, button text ≥4.5. Дополнительно проверяется ровно 8000 ms.
- Seasonal/leap/polar/UTC/date-boundaries, sim/real/fixed, координаты и bootstrap, ручной приоритет, settings race/offline и отсутствие координат в PATCH; explicit consent/denial/forget, digest/PII/run isolation/exceptions.
- Header: `06:00Z→09:00` Москвы, ru/en, invalid/null; общий UTC fmtSim test сохранён.
- `make lint` после ordinary merge: frontend ESLint/typecheck/full Vitest 286/286, Ruff 357 files, mypy 255 modules, OpenAPI drift 192/192 — зелёные. Прежнее предупреждение react-refresh в DemoMenu не добавлено этой задачей.
- Обе production сборки operator/personal проходят.

### Production Playwright с синтетическим локальным transport

`frontend/e2e/circadian.spec.ts`: 5/5 passed, 15.7s. HTTP/WS fixtures отмечены как synthetic и не подменяют actual API proof ниже. Покрытие: оба пакета × все 6 фаз × ru/en; ручной выбор/reload; bootstrap без смены mode после гидратации; реальный 8s requestAnimationFrame; reduced motion; real clock; explicit consent; exceptions; 390×844; три browser timezones (UTC/New_York/Auckland), ru/en, ноябрь и US DST boundary 8 марта.

475 samples реально отрисованных кадров за 7924 ms: минимальный текстовый контраст 4.5000182677, control/focus 3.0000002153. Тест сохраняет frame JSON; 0 page errors/внешних запросов, геолокация только после тестового явного клика.

### Production браузер с настоящим backend API/WS

`frontend/e2e/circadian-actual-proof.mjs`, localhost:18153, отдельная `cx_circadian_revision`, PostgreSQL 16, штатный lite seed 200 синтетических клиентов. Все API и WebSocket настоящие; route mocks отсутствуют. Runtime chain и все три роли проверены как Mock, внешний socket/DNS запрещён тестовым wrapper. Browser timezone America/New_York.

1. До автоматического запуска API `set_speed=60` и явный `jump_to` ставят сим-часы перед seasonal границей `morning/noon`.
2. Настоящий API `start`: состояние `08:29:36.337Z→08:38:06.337Z`, 9 естественных `sim.tick` с `running=true`, `speed=60`, UI `morning→noon`. До отдельного ночного jump_to наблюдались 11 sim.tick: 9 естественных и 2 предварительных command-driven. В полном WS proof записано 20 sim.tick, включая 9 chunk-ticks отдельного ночного jump_to. Новая фаза наблюдалась через 118.4 ms после start; переход палитры затем завершился отдельно за штатные 8s.
3. Настоящие API `pause` и **явный `jump_to=17:30Z`** дают night и Header20:30 Москвы. Это отдельное управление сим-часами, не естественное наступление ночи за 11 тиков и не fixed-источник.
4. Header сопоставлен реальному UTC-часу через независимый Intl Europe/Moscow; после паузы показывает11:38 Москвы. 0 browser errors, внешних запросов, запросов геолокации по умолчанию. Ночная панель показывает public_id настоящих сигналов scratch-прогона.

Четыре actual API PNG в `docs/screenshots/T-252/`, light/dark ru/en, просмотрены. Сырой proof JSON, providers assertion и frame JSON сохранены в `/tmp/vibebashers-t252-*`; полный backend test затем использует только эту же scratch-БД, после остановки сервера.

## Оставшиеся gates

Полный `make test` на собственной scratch-БД завершился exit0 на замороженном `c71a918`: unit1168 passed/18skip, integration245 passed/2skip, scenarios42 passed/2skip, compliance31 passed; суммарно backend1486 passed/22skip и frontend286 passed. После этого bounded frontend-only исправления проходят отдельные полные frontend/production проверки; backend на этих последующих шагах не меняется. Реальный GigaChat в этом пакете не вызывается по явному ограничению родительского задания; общий live DoD составного стенда остаётся у родительского агента. До полного результата, CI, PR/review и merge карточка остаётся `in_progress`; полная приёмка не заявляется.


## Проверка краевых случаев после полного checkpoint

При read-only self-review найдены и исправлены: совпадение bootstrap/runtime fallback при повреждённом новом mode и валидном legacy mode; near-polar dawn/twilight через солнечную полночь (проверяются соседние солнечные даты, explicit polar day/night сохранены); cache scope NightDigest по реальным runs-событиям и live current_run_id, включая запоздалый ответ предыдущего scope. В кеше digest теперь только id/public_id, без полного Signal DTO. NightDigest ссылается на существующее рабочее место `/`, а не на несуществующую отдельную страницу сигналов.

Также интерполируются декоративные border/brand tokens; faint/placeholder в circadian использует читаемый muted, ручные legacy палитры не изменены. Sweep всех дней2026 у обеих полярных областей (lat±60..89, lon−179/0/179) проверяет более200000 границ. Четыре ранее ошибочных midnight boundary зафиксированы отдельной регрессией. Узкий набор после исправлений:147passed; окончательные composed/frontend/browser результаты будут добавлены после ordinary merge main dfbf47a.
