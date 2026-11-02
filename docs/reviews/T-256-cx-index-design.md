# T-256: источники CX Index и план API 1.5.29

Статус: source audit и pure core, не готовая приёмка/API. Ветка `codex/T-256-cx-index`, исходная база clean T-244 `b971710`. T-255 и T-257 будут отдельными stacked ветками/PR. API 1.5.29 зарезервирован; DDL не меняется, CSI20 WIP не используется.

## Утверждённая формула

ТЗ 14.1: `CX = clamp(100 - (w_n*N + w_c*C + w_s*S + w_r*R), 0, 100)`, окно 24 сим-часа, изменение за час. Веса по умолчанию **0.4 / 0.25 / 0.2 / 0.15**, источник `settings.cx_index.weights`. Это демонстрационный индекс, не CSI и не денежная формула.

Pure core принимает все четыре компонента и все веса явно. `Observation(value, known, total)` сохраняет полноту; если компонент неизвестен или coverage неполон, индекс unknown, даже при нулевом весе этого компонента. Веса не перенормируются, отсутствие данных не заменяется нулём. Структурно пустой знаменатель может иметь явно обоснованный 0 (например, нет открытых инцидентов), но пустой сигналовый cohort не означает нулевой средний негатив. Веса конечные, неотрицательные, хотя бы один положительный; используются буквально по формуле без принудительной нормировки. Насыщение промежуточных неотрицательных слагаемых эквивалентно итоговому clamp и защищает от overflow при больших явных весах.

## Проверенные источники и gaps

- N: `signals.classification.negativity`; `agent/nodes.py` явно копирует normalization.negativity в classification. Только валидный записанный процент 0…100, не sentiment-to-score conversion.
- C: записанный `classification.criticality` из high/medium/low. Missing/legacy malformed даёт unknown, не low.
- R: канонический `churn_intent` в записанном classification.flags. Producer выставляет его при hidden_negativity.churn_threat.present или intents churn_threat. Пустой default signals.flags у необработанного сигнала НЕ является доказательством false. Никакого вывода из churn_risk или sentiment.
- `v_signal_normalized` / `v_cabinet_signal_facts` доступны; первая проекция не содержит N, допустимо связывать её IDs с signals 1:1 без DDL. Customer cohort исключает служебный proactive anchor, technical Trace не меняется.
- S требует конкретного semantic review: ТЗ не задаёт численный threshold «риска SLA». Existing dashboard hardcode 2h не равен UI hint 4h и не является утверждённой policy индекса. Предложение: actual current-lifecycle native warning и текущая просрочка; stale/closed/reopened/released/same-clock warning не переносится как текущий риск. Различие «нет зарегистрированного warning» и «полный риск отсутствует» должно быть явно отражено coverage/подписью; количественный threshold не придумывается.
- Для previous нельзя читать нынешнюю classification как прошлое состояние. Immutable `agent_steps.output` у classify содержит native `churn_predicted_sim` и score_pipeline. Предложение: исторические N/C/R только из matching-run snapshot с валидным timestamp до исторического cutoff; без такой provenance — unknown. Previous S требует native deadline/lifecycle evidence, иначе unknown. Никакого скрытого восстановления истории из текущих значений.
- `GET /api/metrics/cx-index` сейчас501 с object schema, `/overview` — PendingScreen. Dashboard и economics/live по умолчанию материализуют экономику: read-only Overview не должен обращаться к этим mutating paths. Есть внутренние refresh=False параметры, но текущие DTO также подставляют0 при unknown. Нужен конкретный typed readonly projection в API29, без изменения денежного producer/default legacy поведения.
- Готового agent shift-summary producer нет. Допустим compendium реально записанных agent summaries с public run IDs, provenance и mode; шаблон нельзя назвать новым текстом агента, LLM для этой страницы не вызывается.
- JuryModal уже создаёт сигнал прежним API и имеет JourneyLink/VoiceInput. Недостаёт города, явной privacy/hint, Trace-действия, полноценной ru/en локализации refs и требуемой доступной раскладки. Это отдельная T-257, не часть backend T-256.

## Порядок реализации

1. Pure core и unit boundaries; затем typed DTO/конкретные API29 semantics и review.
2. Пакетный read-only REPEATABLE READ reader с current-only metrics scope, explicit all, отсутствующий current → empty, без fallback all; customer/run guards до агрегаций. N/C/R, coverage, channel mix, 24 hourly count buckets и наблюдаемые source references. S/previous — только подтверждённые источники.
3. Settings weights: утверждённые defaults только при отсутствии настройки; invalid configuration явно диагностируется, не заменяется default молча. PATCH validation и минимальное изменение typed settings contract входят в конкретный API29 diff.
4. Main/edge/run/legacy/proactive/privacy/readonly PG cases, ручной расчёт, воспроизводимость, cold p95 ≤300 мс и actual EXPLAIN; отдельный functional coverage без timing под tracer.
5. T-255: все девять блоков на реальных typed API, projection «не география», readonly saved money/coverage, chain/Trace/Journey, HITL preview без изменения решений, compendium, темы/пакеты/языки/mobile/a11y.
6. T-257 отдельной веткой: существующий нормализованный POST, city/unknown client/privacy/hint, VoiceInput secure-context guard, реальные переходы Journey/Trace, unit/browser regression.

Новых весов, денежных/HITL правил, внешних вызовов или auth/RBAC не добавляется. Финальные API29 semantics требуют human contract review после конкретного tested PR; показатели CSI из незавершённого T-248 не импортируются. Rollback — отдельный reviewable app revert, БД не меняется.
