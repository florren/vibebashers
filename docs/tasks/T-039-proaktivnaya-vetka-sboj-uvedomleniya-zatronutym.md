# T-039 — Проактивная ветка: сбой → уведомления затронутым клиентам до жалоб

| Поле | Значение |
|---|---|
| Эпик | E3 Симулятор банка, команды, SLA |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
Агент реагирует на fault.started раньше клиентов (ТЗ 6 шаг 4, сценарий 6).

## Разделы ТЗ (docs/TZ.md)
§6, §8.4, §18 сц. 6

## Контракты

`contract-change`: API1.5.25/native scenario events и dependency DDL0019;
final API/DDL/financial/HITL human review обязателен до merge.

- `events/sim/fault.schema.json`
- `events/agent/decision.schema.json (client_action.kind=proactive_notice)`

## Зависимости
- Зависит от: [T-034](T-034-generator-sboev-i-vosstanovlenij.md), [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md), [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md)
- Блокирует: [T-064](T-064-deduplikaciya-i-massovye-incidenty.md)

## Что сделать
1. Подписчик fault.started → создание «служебного» сигнала origin=proactive → граф агента: оценка массовости, создание инцидента incident_type=proactive или tech_fault, выбор затронутых клиентов (по операциям в окне), рассылка proactive_fault по согласиям, установка mass_impact.
2. Дедупликация последующих жалоб к этому инциденту (T-064).
3. Отчёт в карточке: сколько уведомлено, сколько жалоб предотвращено (по модели поведения).

## Критерии приёмки
- [ ] Сценарий 6: 120 затронутых, ≥ 90 уведомлены до первой жалобы, 30 жалоб дедуплицированы.
- [ ] Поведенческая модель фиксирует рост care_score у уведомлённых.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=mass_notifications
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._


### 02.11.2026: prerequisite temporal cause fix

В отдельном focused follow-up World.gen_operations проверяет реальные
fault run/system/code/time/region границы; future fault не создаёт ранний failed
link/жалобу. Порядок RNG draws сохранён, rollback/retry и actual PG positive/negative
случаи проверены: 5 passed. [Отчёт](../reviews/T-039-temporal-cause-follow-up.md).
Это не реализация всей T-039: proactive subscriber/массовый incident/предотвращённые
жалобы остаются отдельной работой; критерии приёмки не помечались выполненными.

Combined adjacent regression: 49 passed (169.73 s), changed executable line
coverage 31/31=100%; source SHA в proof JSON. Полный suite/CI остаётся за
окончательной композицией, completion T-039 этим не утверждается.

## T039 native proactive path: начальный checkpoint

Один internal service signal без личности клиента проходит обычный Mock graph и native consented fanout; actual causal/time/provenance guards и API1.5.25 default-deny внешнего service origin подготовлены. Dependency schema9/owner2PG, ingress13unit, graph/timing5PG, полный unit1787/18skip и contracts45/162 прошли. Automatic wake/recovery/late recipients, actual120/90/30, care proof, итоговые full/coverage/CI и human review ещё в работе. Prevented complaints пока null/not_modelled, не равно Sent. [Отчёт](../reviews/T-039-proactive-fault.md). Статус и критерии всей карточки не объявляются завершёнными.

### Native runtime checkpoint: controlled 120/90/30

Automatic fault wake + durable recheck, один internal service AR, late recipients
через тот же checkpoint, strict causal dedup и metadata link до HITL реализованы.
Controlled own-PG proof: 120 actual same-run YuFO affected, 90 native Sent/emulated
chat строго до первой жалобы; care вырос у тех же90 через production behavior
loader/owner. Все30 последующих normalizer inputs связаны с одним incident,
mass/economics120, 2 human decisions остаются pending; ledger агента пуст.
Native owner фиксирует30 first_complaint. Полный unit1800/18skip и focused PG
concurrency/account/audit/ABS проверки зелёные. [Доказательства и границы](../reviews/T-039-link-lock-order.md),
[машиночитаемый proof](../reviews/T-039-native-mass-proof.json).

Это не успешный `make scenario`: production YAML пока inject3, phased orchestration
предстоит отдельно согласовать/реализовать; 5000-client metadata augmentation и
90/30 consents заданы только own fixture. Prevented complaints остаётся
null/not_modelled; cancellation provenance proposal, customer aggregate composition,
итоговые full/coverage/CI и financial/HITL/API25 human review ещё необходимы.
Статус всей T039 остаётся in_progress, критерии не объявляются закрытыми.

### Scripted scenario candidate

Production YAML/API/worker теперь используют prepared_native и bounded typed
phase journal вместо inject3. Native120/≥90доfirst/30links/care подтверждены
Mock/emulated PG; strict evaluator/unknown delivery/paused recovery и controls
проверены отдельно, ASGI lite409/demo202 проверены. Lite preflight не подменяет
cohort, contacts или consents; для120 нужен достаточный demo профиль.
API25 candidate включает запрет Resume/step/jump/reset для journal-owned run,
Stop/new-run path и узкую strict paused recovery; mandatory human review впереди.
Owner receipt B/prevented-by-resolution, final composition/full/coverage/CI ещё
не завершены; критерии всей задачи остаются unchecked.


### 02.11.2026: отдельный packet prevention receipts B

User variant B разрешён для реализации; final DDL/runtime consumer review отдельно.
Additive0019 после actual0018 хранит nullable versioned детали отмены без backfill
legacy. Owner пишет receipt и status атомарно; внутренний run-scoped reader отличает
modelled resolution до primary due/first complaint от Sent/care/already-complained
и unknown. Сам proactive subscriber/controlled scenario находится в отдельной
ветке T039; эта композиция не помечает карточку целиком done. Проверки и границы
будут зафиксированы в [финальном review receipts](../reviews/T-039-receipts-final-review.md).


### Current native B consumer candidate

Corrected owner dependency0e0db416 подключён обычным merge5920c42; report читает
единственный summarize, без Sent fallback/новой p/delay/care/money policy.
50 targeted PG/unit прошли211.57s: current native120/120Sentдоfirst/30dedup,
care120, modelled prevented-by-resolution0 при complete provenance,
10 уже отменённых already-complained work и40 pending primary. Complete не
означает завершение всех trajectories; это observed-current snapshot.
Legacy NULL receipt даёт None/incomplete, даже при Sent120; immutable phase не
переписывается. Final coverage/full/CI/API25+receipt19 review ещё впереди.
Receipts packet final source0e0db41:2591backend passed/24skip,366frontend,43bot;
changed runtime coverage129/138=93.48%. Targeted T5/T8/T9 native PG доказывает
logical vs observation cutoff и отсутствие credit уже поступившей жалобе.
[Source-qualified proof](../reviews/T-039-receipts-runtime-proof.json).
Final DDL19/consumer review и композиция proactive API25 остаются отдельными;
полная T039 этим отчётом не закрывается. Реальных внешних вызовов/prod не было.
