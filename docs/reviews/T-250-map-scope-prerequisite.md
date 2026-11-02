# T250 — prerequisite operational Map scope

Источник: Python defaults всех трёх Map endpoints — `run_id=None`; общий resolver
и heat Query description уже означают current по умолчанию. Это сохраняется.
Меняется ошибочное расширение отсутствующего current до all, не default backend.
Глобальный `resolve_run_id` не меняется.

Actual PG counterexamples на своей `cx_map_branches_revision`:

- После current_run_id=NULL запрос current выдавал815 baseline сигналов/90 открытых
  инцидентов,10 городских сигналов,59 зональных сигналов вместо пустого operational
  scope (RED9.46s). Omitted до/после существующего current сравнивается с current.
- Fresh free current получал baseline audio alert: critical_count1/copilot_index1.0
  при отсутствии собственных записей (RED8.03s). Fixture — явно synthetic native
  transcript session + immediate alert, без аудио/LLM/отправки уведомлений.

Локальный Map-only scope filter: explicit all не ограничивается; current/omitted
берут прежний current ID либо SQL FALSE при его отсутствии; numeric — positive
bigint; malformed/empty —422 до SQL. Та же граница применяется к signals,
incidents, audio_sessions и no-geo count. Пороги, timewindow и alert producers не
меняются. Региональная геометрия остаётся доступной с нулевыми агрегатами.

Новые2 scope regressions плюс прежние2 map/metrics tests —4passed25.80s.
Проверены все3 endpoints: noCurrent, fresh free, explicit numeric, All, omitted,
invalid/empty, а также foreign audio exclusion и сохранение истории в All.
Ruff/format/Mypy одного producer module зелёные. Полный backend suite не запускался.

Отдельный doc-gap: OpenAPI heat/cities не содержит уже существующий run_id parameter,
zones использует общий RunId. Для review подготовлен additive patch
`/tmp/t250-map-run-params-review.patch`; контракт пока не редактируется, API30 не
занимается. Ещё существующее расхождение enum heat layer: spec incidents_open/churn_risk
против runtime/client incidents/churn; текущий packet его не нормализует молча.

Совместимость UI: новый operational Map default current; All остаётся явным выбором.
Fresh free при существующей baseline истории не должен показывать её как текущую.
Rollback — source revert; DDL/backfill/рабочих данных не затрагиваем.
