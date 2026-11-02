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
