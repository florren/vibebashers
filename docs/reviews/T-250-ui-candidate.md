# T250 — UI candidate до native/performance proof

База — собственная CSI/T2624a8 с обычной композицией опубликованного T249c284,
root T2625525 (evaluator348) и whitespace/proof4ac. Чужой WIP не копируется.
API30 пока не применяется: final API29 parent ожидается от владельца.

Реализовано в candidate:

- One-click lazy ВСП; typed API28 DTO и paginated directory, TTL24h по scope/headers.
  Менеджерский binding отправляется только для product_manager; server preset
  остаётся источником фильтра. Смена role/run не использует старый placeholder data.
- Детерминированные CSS-pixel clusters под signal group. Anchor — исходная точка
  реального ВСП, без среднего/jitter. Zoom и клавиатура; совпадающие точки доступны
  списком. Invalid/null координаты не становятся0 и явно учитываются отдельно.
- Четыре exact data colours/types. Тихая closed подпись берёт только native direct
  BranchDetail.signals.total. Отсутствующий/error/noCurrent snapshot — unknown,
  не0. Счётчик доступен и в списке co-located branches.
- Background detail reads bounded3, selected detail ещё1; metrics cache15s,
  cancellation не запускает следующую партию/не публикует старый scope.
- Карточка: native address/hours/status, direct signals/CSI/sample, typed scoped
  internal trace links. Employee contacts/FIO/source_url не добавляются.
- Отдельные pressure heatmap, server-configured deficit, network12mo и closure-zone
  table с фильтром. NULL не превращается в0, отсутствующий threshold не выдумывается.
  City/region90-day zone counts не выдаются за direct counts/unique sum.
- Operational Map default current; All остаётся явным. Explicit blank/invalid scope
  не теряется в qs(); API read guard вынесен отдельными prerequisite commits.

Подтверждено только targeted:28frontend tests (geometry11, API5, widgets3,
Map controller3, existing CSI6), typecheck, targeted ESLint, i18n parity2209 keys
и unchanged authoritative generated TS. Native backend scope/layers6cases отдельно
в prerequisite review. Это не полный backend/frontend green.

Ожидаются ресурсное окно production build/native browser, обе темы/языка, strict
map-layout regression, read-only fingerprints/zero egress и фактический demo≤3s
замер. Нельзя считать3s доказанным по unit duration или скрыть count reads из timing.
Если existing bounded detail path не уложится, batch API сначала предлагается
конкретно с результатом измерения; сейчас новый endpoint не придуман.

Дальше — ordinary composition final API29, additive API30 (RunId/оба слоя aliases),
генераторы/контракты и final scoped regression. Карточка T250 не done; T262 overall
также остаётся pending до обязательных UI/replay checks.

## Финальная композиция и native proof (03.11.2026)

Позднее включены clean API29 c8, T255192 и Journeyc463 обычными merge; ранее
описанное ожидание API29/окна относится только к исходному candidate07e.
[Конкретный API30/compatibility diff](T-250-api30-review.md) и
[native evidence](T-250-native-proof.json) относятся к финальному runtime.

Своя fresh `cx_map_ui_revision`: actual migration20, demo5000,600000 seed operations,
затем настоящий T262 XLSX→normalizer301 inputs,300 registered members/2400 visits.
Исходный корпус не менялся. Mock-only APP_ENV=test; реальный paused Simulator
загружен до fingerprint, поэтому Header/ScopedRunBoundary не скрываются за503.
Actors не запускались. Единственная browser interception — presentation ui в
GET settings (theme/layout); бизнес-ответы API настоящие.

4cold contexts ru/en×light/dark: initial296–323ms; toggle→полная pagination,
analytics и все19closed background reads718–752ms. Это4 замера, не статистический
p95. Selected detail —20й read, после замера. S0016 direct1 совпал с подписью
co-located списка и карточкой/scoped trace links. Его cohort denominator честно
unknown: extra1 не приписывается к300 зарегистрированным. Ни city-zone count,
ни directory network history не выдаются за direct linkage.

Все97таблиц fingerprint равны до/после4cases,0external/nonGET/JS/HTTP errors.
Первый probe выявил3ожидаемых abort при pagination: теперь closed fanout стартует
только после полной directory, final0abort. Native visual также выявил обрезание
длинной sample подписи; локальный dl карточки показывает полное поле/unknown.

Portable `e2e/map-branches.spec.ts`:4/4 за6.6s (one-clickon/off, native direct
counts, co-located membership/card/scoped links, GET-only). Исходный строгий
`map-layout.spec.ts` без изменения assertions:20/20 за15.9s на5viewports/2языках/
2темах. Визуально просмотрены map/card PNG обеих тем/языков.
`make lint` exit0:511front/74files, backend557/325,bot12/5,drift196/196;
contracts48schemas/166paths; обе production сборки green. Финальный full backend
regression/CI и human contract review ещё обязательны; не заявляем полный DoD.

### Открытая visual граница после PNG review

На overview PNG центр cluster count совпадает с некоторыми heat value labels
(например Moscow area в en-light). Порядок SVG групп корректный, но наложенные
цифры трудно читать. Это не скрывается отсутствием HTTP/JS ошибок: финальная
visual приёмка требует scoped presentation correction count glyph без сдвига
native anchor/координат, затем нового build/native proof. Эти PNG и времена
остаются доказательством исходного runtime; не приписывать им будущий фикс.
