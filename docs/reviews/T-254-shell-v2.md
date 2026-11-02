# T-254: флаговый каркас v2

Отдельная stacked-ветка `codex/T-254-shell-v2` поверх T-253 `e61ce53`. Все изменения T-253 объединены обычными merge; опубликованная история не переписывалась. Backend, API/DB contracts и scripts совпадают с полным backend-прогоном T-253 `59da3d3`.

## Реализация

- `ui.layout=legacy|v2`, default `legacy`; существующая typed GET/PATCH settings map, та же сериализованная очередь PATCH отдельных `ui` ключей, сохранение несвязанных полей. Переключатель доступен в `/setup` → «Оформление интерфейса»; в v2 доступен также внизу Sidebar. Отключение флага возвращает прежний Header/Workspace.
- Четыре группы ТЗ 26.4: операционный контур (6 адресуемых пунктов, включая отдельные «Карта»/«Зоны»), контроль/аудит, демонстрация, продукт/сеть. Сохранена дополнительная ссылка на существующий `/finance`: это другой экран, чем `/economics`. Старые маршруты остаются доступны напрямую.
- Только index `/` с включённым v2 переходит на `/overview`; index с legacy `?tab=...` переходит на `/workspace` с полным сохранением query. Без флага index не перенаправляется. Состояние зон карты действительно задаётся `map_mode=zones`, а не только подписью меню.
- Переиспользуется существующий Header со всеми simulation/search/jury controls: Moscow clock/phase, настоящий numeric run id и label из DemoStatus, LIVE означает WebSocket, режим LLM отдельно берётся из DemoStatus. В мобильной шапке остаётся компактный номер запуска, полная label доступна в меню — header сохраняет лимит 100 px.
- Sidebar видим от 1024 px, ниже — off-canvas через существующий Drawer с focus trap/Escape. Прокручивается navigation, SystemStatus и выключение layout закреплены. Status раскрывается native details, показывает реальные health/demo поля; это конфигурационная готовность, не утверждение об успешном внешнем LLM probe. При отсутствии данных — unknown, при ошибке — явное сообщение.
- `1–6`, `/`, `Ctrl+K`, `?`; справка и Escape. Numeric keys не перехватываются в input/textarea/select/contenteditable, при модификаторах, IME и открытом dialog. Сохранены существующие GlobalSearch handlers.
- Пресеты роли — только frontend union кодов ТЗ 24.1 с типом существующего `CxRole` header. Сейчас `/api/roles` имеет generic DTO и backend501, поэтому ответ не подменяется и новый endpoint/серверная роль не создаётся. Пресет меняет меню/подсказки/attention default; прямые адреса остаются доступны. Presenter — отдельный локальный контекст. Изменение/снятие локального пресета отменяется Undo 8s без серверной мутации. RBAC и кабинетная фильтрация не объявляются реализованными.
- В calm v2 средняя desktop ширина использует 4 колонки KPI, сохраняя целые 16px подписи; при большой ширине — 8. Legacy/mobile/control_room раскладки этим CSS не меняются.

## Проверки и исходники

- `80f569a`: полный `make lint` — frontend323, Ruff368, mypy257, drift192/192. Production **53/53**: 49 существующих read-only legacy regressions +4 actual v2 ru/en×light/dark.
- Финальный runtime `18de30f`: полный `make lint` (frontend325, Ruff368/mypy257/drift192) и **325/325 Vitest**, ESLint/motion guards/typecheck, обе production сборки. Backend/контракты не менялись; полный backend **1663 passed /22 skipped** получен на побайтно том же backend tree в T-253 `59da3d3`. Новый полный backend suite для frontend-only пакета не повторялся.
- Последующие целевые actual cases проверяют real settings PATCH и сохранение sentinel, on/off, query-preserving redirects, все 6 numeric keys, `/`/CtrlK/help, защиту typing/dialog, роль+локальный Undo, `/finance`, system readiness details, widths1920/1440/1024/768/360/320, focus/Escape и отсутствие горизонтального overflow. Строго проверяется SVG bottom ≤ viewport, в том числе1024×768; порог не повышался.
- Существующий legacy mobile test запускается отдельно с явно выключенным layout flag. Первоначальный запуск на оставшемся после прерывания v2 показал header131px; полная label убрана только из компактной шапки в меню, а assert100px сохранён и добавлен к actual v2320/360.
- Браузер работает с настоящим actor-free FastAPI и отдельной `cx_shell_ui_revision` (schema0011, штатный lite200), без HTTP подмен в новых v2 cases. Guarded preview запрещает LLM и внешние sockets/DNS; browser запрещает external и non-settings business mutations. Настоящие settings PATCH намеренно разрешены. Старые mobile regressions используют свою существующую read-only theme fixture; это отдельный источник доказательства.
- Ноль попыток external/LLM и запрещённых browser mutations. **DB unchanged не утверждается**: inherited GET economics materialization описана в T-253 и не исправлялась здесь.
- Контракты45/OpenAPI162, i18n1856, generated TS не меняется. Карточки205 — generator idempotent. Владение L4 соблюдено, кроме нового `frontend/e2e/shell-v2.spec.ts` (L5): разрешённый пользователем cross-layer, PR требует соответствующей метки/описания.

## Незакрытые зависимости

`/overview` (T-255), `/cabinet` (T-242) и `/csi` (T-249) в этой базе ещё не реализованы. Именованные availability routes явно говорят о готовящемся экране и дают ссылку на настоящее workspace. Здесь нет выдуманных KPI, индексов, CSI или кабинетных таблиц, нет redirect loop. Это временная граница dependent stack, не финал общей задачи all94: целевые страницы обязаны стать настоящими в своих карточках. Их приёмка и budget≤9 не закрываются T-254.

Пакет также зависит от финального human review UI-HITL изменений T-253. До review/CI карточка остаётся `in_progress`, push/PR/merge выполняет parent.


## Итоговое доказательство `18de30f`

Actual v2 **4/4 passed (33.9s)**, ru/en×light/dark, widths1920/1440/1024/768/360/320: реальный saved flag и control_room, local preset Undo, все6 numeric shortcuts, / и CtrlK, помощь, typed-field/dialog guards, `/finance`, readiness details, map bottom≤viewport включая1024×768, mobile header≤100px, focus/Escape, ноль запрещённых запросов. Новые ответы API не подменялись. Отдельный legacy320px source e171: **4/4 passed (40.0s)** на исходных assertions после явной установки legacy fixture. Последнее исправление меняет только v2 footer typography/spacing; legacy CSS ветка сохранена.

В `docs/screenshots/T-254/` сохранены и просмотрены16 PNG: четыре legacy «до», четыре v2 calm desktop, четыре control_room desktop, четыре v2 mobile. `proof.json` фиксирует source SHA/объём. Первый legacy ru/light кадр также показывает штатное loading-состояние KPI; это доказательство layout, не утверждение о нулевых метриках. Перед съёмкой v2 rows загружены. Preview18159 остановлен; scratch БД сохранена для повторения, canonical main и чужие worktrees не изменялись.
