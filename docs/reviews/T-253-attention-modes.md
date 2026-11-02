# T-253: режимы внимания и обратимость UI

Код: `59da3d3` + frontend follow-up `747bd92`, обычная композиция `bd649f2`. База — согласованный T-252 `241a174`. Backend, contracts, data и финансовая/HITL policy не изменены.

## Что реализовано

- `ui.attention=calm|control_room`, `null` означает выбор по контексту. Существующие GET/PATCH `/api/settings`, валидированная гидратация, очередь PATCH только изменённых вложенных ключей `ui`, защита от позднего GET и сохранение несвязанных настроек. `brand`/`cx_lead` и кабинет/`product_manager` по умолчанию тихие; `ops`/явный контекст демонстратора — ситуационный. Сам селектор контекста/роли подключается в T-254; новые серверные роли не создаются.
- `PriorityStrip`: настоящие активные инциденты текущего запуска, сортировка API `priority`, максимум три, ручное переключение. При перестановке элементов выбор сохраняется по реальному ID; новый run не использует placeholder старого списка. Тексты/ПДн инцидентов не копируются в полосу.
- `SlaWarning` в доске/таблице и карточке инцидента: абсолютная разница `sla_due_sim - sim_time`, конфигурация `settings.sla_warn_hours`, по ТЗ default 4. Ровно 4 часа включаются; завершённые статусы и невалидные часы исключаются. Сим-часы приходят из существующих API/WS. Это UI hint, не изменение существующей серверной политики warning в 1 день. Округление вверх: реальный остаток 2.733 ч отображается «Срок через 3 ч» / «Due in 3 h».
- `UndoToast` восстанавливает только локальный снимок фильтров и закрытые панели; окно ровно 8 с, новый undo заменяет прежний, истёкший callback не выполняется, навигация сбрасывает неприменимый undo. В Undo нет сетевых мутаций и обещания отменить серверный результат.
- HITL submit и закрытие инцидента в тикетнице предваряются именованным модальным подтверждением с последствиями. Cancel ничего не отправляет; Confirm использует исходный endpoint/payload. Уже решённый/невозобновляемый HITL повторно не отправляется. Денежные инструменты, лимиты, HITL права и backend validation остаются прежними.
- Конечные переходы 300/400 мс, подъём карточки 2 px; индикатор ситуационного режима затухает один раз за 1.5 с. Бесконечные pulse/spin убраны. При reduced motion CSS полностью отключает animation/transition (исходные 0.01 мс оставляли реальную running transition). Исключения `/manager`/`/compliance` сохранены; звук не добавлялся.
- Словарь заботливых ошибок и следующего шага пустых состояний ru/en, исходные технические подробности остаются в details. Семантические `data-block`, общий лимит 9 и тест, который отклоняет десятый блок.

## Подтверждения

- Полный `make lint` на `59da3d3`: 311 Vitest, Ruff 368 файлов, mypy 257, drift 192/192, ESLint и отдельные motion guards.
- Полный `make test` на замороженном `59da3d3`, собственная `cx_attention_full_revision`: backend **1663 passed / 22 skipped** (unit 1323/18, integration 266/2, scenarios 43/2, compliance 31), frontend 311. Предусмотренные пропуски внешних/live проверок не выдаются за live proof.
- Финальный frontend `747bd92`: **312 Vitest**, ESLint/motion guards/typecheck и обе production сборки зелёные. Backend/контракты побайтно совпадают с полным прогоном; повторный полный backend suite для CSS/selection-only follow-up не запускался.
- Production `59da3d3`: **49 существующих browser regressions** прошли, включая строгую геометрию карт и все размеры mobile. Первые 3/4 новых calm cases выявили reduced-motion defect; он исправлен кодом, assert не ослаблен.
- Production `747bd92`: **4/4** calm cases с настоящими API/settings (ru/en × light/dark): сохранение режима/перезагрузка, локальный reset/undo, ≤9 блоков реального workspace, ноль infinite animations и ноль running reduced-motion animations, menu/Escape на 360 px, исключения manager/compliance. **Ещё 4/4** actual SLA list/detail + mobile focus cases, без подмены HTTP.
- Отдельные UI БД и full-suite БД; source/full suite не редактировался во время выполнения. Для UI штатный lite seed 200 + четыре обращения через настоящий normalizer/Mock graph до браузерного этапа. Во время браузерного просмотра LLM и external network запрещены guarded preview; actors не запускались. Preview после проверки остановлен.

## Выявленный побочный эффект существующего GET

Нельзя утверждать «DB unchanged»: при дополнительных GET list/detail economics совпали 83 из 85 table fingerprints, изменились `incident_economics` (154 → 154 строк) и `db_activity_log` (+104 строк). В этом дополнительном SLA/mobile проходе браузер не пытался отправлять non-GET команды; изменение порождает существующая GET materialization. Отдельные calm settings cases, напротив, намеренно выполняли и проверяли настоящие PATCH ui.attention; эти разрешённые настройки не включаются в утверждение о нуле non-GET. Отдельный HTTP 200 `GET /api/incidents/{id}/economics` подтвердил изменение **только `computed_at`** и +1 audit row; остальные колонки, включая финансовые результаты, сохранили hashes. Безопасные имена/count/hash — в `get-economics-materialization.json`, без raw payload. Backend в T-253 не исправлялся; finding передан владельцу economics.

## Приёмка и ограничения

Изменения подтверждения HITL требуют финального human review по AGENTS; это review UI diff, а не разрешение изменить денежную policy. Карточка не помечена done до такого review/CI.

`/cabinet` (T-242) и `/overview` (T-255) ещё отсутствуют в этой базе. Бюджет блоков и семантическая разметка готовы, реальный workspace проверен, но приёмка этих двух будущих экранов не объявляется выполненной. Пресеты роли также не являются RBAC.

Снимки относятся к `747bd92`: четыре desktop calm, SLA ru/light и en/dark, mobile 360 ru/light и en/dark. Файлы в `docs/screenshots/T-253/`; пользовательские тексты seed остаются на исходном языке и не являются результатом локализации содержимого.


## Уточнение ErrorBox (`1f073b6`)

Обычная ошибка протокола/локальный TypeError больше не называется ошибкой соединения. Generic unknown использует нейтральную формулировку, исходные управляемые details сохранены. Только отклонение внутри известной границы `fetch` получает тип `ApiConnectionError`; raw URL/токены transport exception не отражаются в UI, нового логирования нет. HTTP `ApiError` и `AbortError` сохраняют прежнюю семантику. Target13/13, финальный frontend315/315, lint/type и обе production сборки зелёные. Backend и OpenAPI остаются побайтно теми же, что в полном прогоне59.


## Согласование срока SLA с Header (`7bbdd1b`)

Visual proof показал старое UTC отображение `sla_due_sim` рядом с уже московским Header: deadline08:44Z выглядит прошедшим относительно09:00MSK, хотя реальный срок11:44MSK и остаток2.733ч. Только срок SLA в IncidentCard/IncidentPage переведён на существующий `fmtSimMoscow` с явной подписью МСК/MSK. Generic `fmtSim`, created/history timestamps, серверная матрица и warning policy не менялись. Component/format targets15/15, полный frontend317/317, lint/type и обе builds зелёные. Actual API/browser4/4 проверили date+relative hint в list/detail при device timezone NewYork/Tokyo; обновлены два curated SLA PNG и `actual-sla-mobile.json`. Остальные timestamps истории остаются предметом отдельной общей ревизии; эта правка не утверждает их преобразование.
