# T039: предложение production scenario6 (пока без реализации)

Статус: decision proposal. `5a28bbe` содержит controlled own-PG120/90/30,
но `make scenario ID=mass_notif` сейчас не проверяет этот путь: canonical id —
`mass_notifications`, YAML inject3, complaints/preventive_notice в NOT_YET,
evaluator считает `ok=None` допустимым. Подменять3 inputs числом120 нельзя.

## Источник и preflight

Новый typed раздел YAML описывает подготовленный fault case: existing code
NOTIF-DELAY/system notification_gw, YuFO, cohort120, subsequent complaints30,
minimum pre-complaint Sent90 и три существующих complaint text/channel templates.
Duration задаётся явно в YAML для native fault schedule; missing duration — ошибка,
не silent fallback90. Никаких gold/classification/decision/model responses.

До fault/op/service writes выбираются120 РАЗНЫХ actual active YuFO клиентов
с соответствующим active product. Нельзя выбирать segment/severity для обхода
HITL. Проверяются source/routing/team catalog, consented recipient eligibility,
текущий run/profile/maintenance ownership. Insufficient cohort/consents дают
явный preflight failure: использовать documented demo profile; lite не обещает
достаточный pool. Ни duplication, ни перемещение клиентов между регионами,
ни изменение production consents/preferred channel не допускаются.

## Технический выбор до кода

1. Наблюдаемый свободный clock: обычные ambient generators и часы продолжают
   работу. Фазы используют реальные native ops/Sent/complaints. Это минимум
   изменений, но высокая скорость/медленная модель могут дать жалобы до90Sent
   или >30 жалоб. Evaluator обязан честно fail/incomplete, а не возвращать часы
   назад, подавлять естественные complaints или выдумывать120/30.
2. Рекомендуемый для воспроизводимого deferred scenario — явно scripted case:
   `start_paused=True` уже поддержан внутренним run_scenario/Simulator, но ещё
   не включён в публичном scenario path. Источник операций/faults для ЭТОГО
   scenario run — prepared native rows, не одновременно ambient generators.
   Это должен быть явный run-scoped source mode из data, не временное изменение
   глобальных intensities с риском оставить следующий free run выключенным.
   Clock advances через существующий atomic engine/owner path между фазами;
   policy p/delay/care/severity/thresholds не меняются. Технические manual phases
   из proof (1 и0.1sim-minute) должны быть явно описаны как script timing,
   не новые business delays. Новый source-mode/phase guard потребует отдельного
   cross-layer review до реализации; сейчас его в runtime нет.

Рекомендуется вариант2 для `make scenario`, вариант1 остаётся обычным free-run
наблюдением. Переключать режим/замораживать часы молча по скорости модели нельзя.

## Предлагаемые фазы (после выбора режима)

- Prepared: одна короткая TX — native fault.started с полным schedule,
  120 actual failed operations и owner capture/episodes; deterministic source
  external IDs. Нулевой impact до operations не завершает фазу навсегда.
- Awaiting notices: один service anchor проходит обычный graph. Длительные
  model awaits вне sim/incident/phase locks. Учитываются только реальные native
  Sent/delivered с sent_sim, consent и strict same-run/fault/client lineage.
  queued/failed/suppressed/unknown не равны delivery; unknown не auto retry.
  Early complaint/resolution/inactive owner фиксируются как failure/incomplete.
- Complaints: после подтверждённых90 native pre-first notices и фактического
  следующего clock boundary —30 normalizer inputs с exact native source op/fault,
  используя исходные templates. Никаких forced classifications/HITL accept.
  В scripted case следующий clock target обязан быть раньше earliest actual
  pending primary due; если это уже не так или появилась естественная complaint,
  фаза fail/incompatible, не удаляет её и не меняет delay. В наблюдаемом free-clock
  режиме extra natural complaints учитываются и могут дать честный fail exact30.
- Evaluated:30 distinct canonical complaints имеют native incident_signals к
  тому же fault incident; mass и economics actual120, care90; pending human
  показан честно. Неисполненные human actions не объявляются resolved.

## Durable state и restart (предложение, не новый интерфейс в коде)

Append-only typed `scenario.*` events в existing sim_events вместо нового DB
queue/table или переписывания settings_snapshot. Новый payload schema и family
registration обязательны: envelope сам не типизирует неизвестное семейство.
Prepared event хранит scenario/run/fault, фиксированные native operation IDs,
source mode и script version. Последующие receipts ссылаются на prepared event,
service AR/checkpoint и actual notification/customer IDs. Payload bounded ровно
cohort120/complaints30; проверить размер PG NOTIFY, не обрезать доказательства.

Один advisory phase lock и current-run/status scope в short TX сериализуют
worker/restart; нормализатор external IDs и receipt lookup делают повтор
идемпотентным. Phase lock не удерживается через LLM/HTTP. После рестарта факты
перечитываются из native sources; Python Event — только wakeup. Нельзя создавать
новый AR вместо deferred checkpoint или переисполнять act/refund/gift. Нельзя
продолжать foreign/inactive run, auto-accept HITL или retry unknown delivery.

## Evaluator/CLI и лимиты

Для этого scenario обязательные phase/cohort/pre-first/dedup/care checks должны
быть `True`; None/нет phase/неполный cohort не являются passed. Raw AR/token/Trace
остаются полными; customer aggregates исключают origin proactive отдельно.
Scope incident — actual fault, не все случайные incidents запуска. Отчёт сохраняет
Sent/emulated distinction и prevented=null/not_modelled, не Sent=prevented.

CLI ждёт phase completion, а не len(inject)=3 AR; timeout даёт incomplete/failure,
не бесконечный loop/retry. Existing request/provider caps и quotas не меняются;
service pipeline один, customer pipelines ровно по фактическим input IDs.
Добавить data-driven alias `mass_notif` либо исправить card command на canonical
id; не переименовывать existing API id. До human/API25/cross-layer review этот
proposal не считается реализацией production scenario и completion T039.
