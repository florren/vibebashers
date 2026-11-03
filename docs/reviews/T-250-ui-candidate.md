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

### Visual follow-up проверен

После checkpoint f98 число участников смещено только на18CSSpx ниже native
anchor (22px цепляло нижний clip edge), neutral cluster ring прозрачен: в dark
mode он больше не затемняет heat value. Координаты/anchor/radius/toucharea44px,
aria и полный список участников прежние. Отдельная регрессия проверяет native
transform, touch circle, отсутствие заливки, отделённую baseline текста и
keyboard activation того же cluster.

Повтор production main/personal build и4native contexts green: initial298–321ms,
все directory/analytics/19closed reads729–754ms;97table fingerprints unchanged,
0HTTP/JS/nonGET/external errors. PNG обновлены и просмотрены, clip/наложение цифр
устранены. Предыдущие718–752ms/PNG относятся только к f98 и доступны в Git history.
Full `make lint` теперь512front/74files; backend557format/325mypy,bot12/5,
OpenAPI drift196/196. Новый итог не приписывается старому20case strict-map proof:
тот был на f98 при выключенном слое ВСП; glyph покрыт4target unit/native4.

### Portable isolated e2e preparation

`map-branches.spec.ts` — serial settings project, после read-only workers.
BeforeAll один раз требует явный `E2E_ISOLATED_SCENARIOS` и localhost disposable
stand, затем GETstate проверяет paused clock и штатный
`POST /api/scenarios/csi_and_branches/run` создаёт named Mock counters run.
Native require_mock(capture) проверяет **effective всех3ролей до эффектов**;
не изменяем настройки provider, не принимаем HD, не делаем baseline reset/delete.
Clock before/after равен; новый current намеренно остаётся текущим в isolated
CI project до его cleanup. Previous current не восстанавливается SQL/фиктивным
resume: его история сохраняется штатным lifecycle. Marker — утверждение
оператора об ownership, не механизм авторизации приложения. В app.env/config
он не добавляется, только в environment Playwright от собственного ci_compose.

[Actual self-preparation evidence](T-250-selfprep-proof.json): API202, run4 изrun3,
все3роли Mock, paused/sameSimTime; histories2/3/4 содержат по301signal. После POST
четыре browser cases GET-only прошли за8.5s. Нативный detail запрашивается для
каждого closed code последней directory page: краткий pendingHTTP=0 между batches
не считается completion. Positive direct>0 assertion сохранён.

Без marker — ожидаемый отказ **до POST**,97fingerprints и current4 неизменны;
это успешная отрицательная проверка, не ошибочно объявленный зелёным pytest/e2e
exit. CI helper17pure tests passed0.06s; Ruff helper с project config120 green.
E2E TypeScript green с `--lib ES2023,DOM,DOM.Iterable`: прежний e2e config без
DOM.Iterable даёт ошибки существующих Headers/NodeList; исходный config не меняли.

Для своего disposable Mock стенда:

```bash
E2E_BASE_URL=http://127.0.0.1:18161 E2E_ISOLATED_SCENARIOS=own-scratch \
  npm exec -- playwright test e2e/map-branches.spec.ts --project=settings --no-deps --workers=1
```

Команда меняет current на новый named run и сохраняет history; не направлять её
на рабочий стенд. Изолированный production image CI ещё должен подтвердить
композицию с настоящими фоновыми actors; APP_ENV=test proof их не запускал.
Exact-head full backend/CI и final human API30 review всё ещё обязательны.

Final exact-source portable invocation после trim guard:4/4,0skips/0flaky за8.4s,
API preparation run5 изrun4; attachment IDs/clock и SHA256 отчёта сохранены в
selfprep proof. Дополнительный whitespace marker также отклоняется до POST,
97hashes/current5 неизменны. Следующий обязательный этап — actual fresh-image
seed→baseline completed/stopped→native selfprep4; этот APP_ENV=test результат
не выдаётся за image/actors proof. Guard проверяет running=false, не требует
искусственного paused статуса предыдущего header.

### Actual image: подготовка отдельно от UI budget

Clean runtime0a6 после обычных root202/201 merges собран в dedicated `:ci`
imageb98d…; новый strict isolated project подтвердил фактический fresh
`baseline/completed`, running=false, без подгонки status/current. Initial API
preparation прошла. Первый UI run упал на `response.json ProtocolNoData`;
[исходный stack/fresh-state evidence](T-250-image-first-attempt.json) сохранён,
это не объявляется доказанной единственной race причиной. Второй probe выявил
ошибочное предположение harness о total; typed lists теперь обходятся только
через реальные items/next_cursor≤500, без нового API поля.

[25s RED с native counters](T-250-image-backlog-attempt.json): все301signals и
301durable received events сохранены; обработано188primary AR/distinct188,
active4/failed0. UI фаза ещё не запускалась. Это очередь реальных301graphs,
а не ошибка/потеря полученных входов. По этому измерению root технически
согласовал новый preparation bound60s и только beforeAll hook75s. UI tests30s,
Map≤3s/API300ms guards и business параметры не меняются; retries/HD accept/
forced outcomes/LLM fallback отсутствуют.

Stabilization использует kind=agent и точное равенство301source IDs множеству
primary AR.signal_id; missing/duplicate/foreign/failed0, все outcomes non-null.
Awaiting_human/deferred допустимы, human решения не принимаются. Previous active
AR проверяются по всем страницам до POST. Native clock/current/paused повторно
проверяются после очереди. Network diagnostics сохраняют request status,
requestfailed/pageerrors/body read errors; rejected promise обязательно await,
не подменяется empty success. Actual image4 всё ещё pending до успешного повтора;
свои failed projects/volumes полностью очищены, primary/prod не затрагивались.
