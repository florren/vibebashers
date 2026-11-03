# T-161 — runtime phase1, до полной activation

Actual0017 и dependency chain закреплены28c26f8; strict schema inventory follow-up
09655b6 прошёл9PGschema/downgrade/reapply tests. VariantA принят пользователем и
зафиксированd4f810a: legacyrisk сохраняется, rawhazard отдельно.

Phase1 подключает BehaviorOwner к Sim tick с общей transaction/RNG: preflight
раньше World/time/day/RNG effects; native failed operations/evidence, timers,
care/events/signals/RNG фиксируются вместе. Legacy непустой run без marker
отклоняется, новый run получает marker в create_run TX. Fresh пустой run получает
marker атомарно; injected tick failure откатывает marker и memory/DB state.

World timers, ещё не относящиеся к owned failed-op complaint (client_error/QR),
сохраняются с явным client snapshot и consumed receipt. Новый процесс продолжает
их из actual0017, а emission идёт через normalizer без gold/генераторной
classification. Normalizer сам создаёт publicpost, adapter второйpost не создаёт.
Agent graph получает evidence sink по marker; Twin handled callback сохраняет
legacy care поведение только для не-owned run. Paused manualstep разрешён явно;
interrupted run требует resume. Quota hooks не активированы.

19 actualPGruntime/owner tests passed118.35s на своейcx_behavior_revision:
новое соединение продолжает complaint и Worldtimer без повторного signal,
legacy preflight не меняет World/time/day/RNG/DB, fresh marker rollback/retry,
прежние owner/concurrency/Twin/care/SLA/agent scope guards. Это source-qualified
phase1 proof, не полный suite/OSprocess/archive/activation proof.

`enabled=false` сохраняется до coherent full proof. Следующая согласованная
граница: already-complained classifiedsignal без failed-opFK, canonicalproducer
provenance, receipt-before-patience без backdated p_complain/delay. Положительная/
нейтральная консультация без canonicalchurn/repeat не открывает эпизод. Эту границу
phase1 пока не реализует и не объявляет поддержанной. Fullsuite/frontend/CI и
финальный конкретный DB/runtime review впереди.
