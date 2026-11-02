# T250 — API1.5.30 и operational Map: concrete contract-change review

Обычная композиция: clean API29 `c8fc85da`, T255 `192267bf`, scoped Journey
`c463cdda`. При merge API29 единственный конфликт контракта — info.version;
сохранена1.5.29 до собственного additive изменения1.5.30. Ни DDL, ни private
runtime namespaces, деньги/HITL/LLM-политики не меняются.

## Конкретная граница API30

- `/api/map/heat` и `/api/map/regions/{code}/cities`: существующий `RunId` query
  теперь присутствует в OpenAPI; общий resolver не изменён. Omitted PythonNone
  по-прежнему означает current. Explicit `all` сохраняет историю; noCurrent
  возвращает пустой operational результат, не расширяет scope.
- Heat enum содержит прежние документированные `incidents_open`/`churn_risk`
  и прежние runtime/UI aliases `incidents`/`churn`. Обе пары вычисляют один слой.
  Неизвестный layer теперь422 вместо вводящего в заблуждение silent signals;
  это совместимое поведение всех валидных клиентов, более строгая граница
  невалидного входа. Heat/cities документируют `422 Problem`.
- Уже согласованный Map-only filter распространяется на audio_sessions в cop
  CTE. Foreign/baseline alert не становится current alert. Пороги/окна прежние.
- Generated TypeScript обновлён авторитетным `npm run gen:types`.

[Machine-readable proof](T-250-native-proof.json) содержит побайтово равные
canonical JSON представления всех155 schemas API29 и167 schemas API28
(0 изменённых/удалённых DTO, включая CX/CSI/branches/report); SHA256 приложены.
Canonicalization сортирует ключи, не удаляет значения/поля.

## Граница consumer

`WorkspacePage` только для `tab=map` без run_id делает replace URL→current
**до** монтирования WorkspaceContent. Поэтому legacy KpiStrip и его mutating
GET economics не успевают стартовать. Explicit run/all/invalid/empty проходят
существующую read-only ScopedRunBoundary; defaults других вкладок прежние.
Map работает с resolved ID, но показывает selected current из URL. Четыре
регрессии проверяют отсутствие legacy mount, сохранение режима карты и
передачу explicit all/empty/malformed без подмены.

## Проверки и ограничения

`make lint` exit0:511frontend/74files,557backend format/325mypy,12bot format/5mypy;
OpenAPI drift196/196, contracts48schemas/166paths. Production main/personal
builds green. Native proof и6ранних PG scope/alias cases описаны отдельно;
последние относятся к source731af38/0387d24, не заменяют full regression finalhead.

Нужны final human contract review и полный CI точного опубликованного head.
Этот документ не означает merge approval. T250 пока in_progress.

## Rollback

Изменение не мигрирует данные и не пишет бизнес-данные при просмотре. Rollback —
обычный revert T250 feature commits/PR с сохранением parent API29/T255/Journey;
не восстанавливать БД и не откатывать чужую цепочку migrations. Возврат старого
UI также возвращает его известную менее строгую Map scope семантику; при таком
rollback не заявлять current/read-only гарантию этого пакета.
