# T241 — проект контракта API 1.5.22 / DDL18

Пакет требует `contract-change`, `cross-layer` и human review по AGENTS §5.1/7: затрагиваются новый публичный DTO и аудит человеческих решений. Денежные формулы, решения HITL, разрешения и лимиты не меняются.

## Предлагаемый diff

- Типизированные `CabinetOverview`, `CabinetSignals`, `CabinetRoles`; новый read-only `GET /api/cabinet/signals` (sort/date/region, filters, limit≤200, bounded offset). `run_id=current` включает baseline + current; отсутствие current не снимает scope. `all` — явное действие. Период от sim_time, группировка Europe/Moscow.
- Preset headers — фильтр, не RBAC: cx_lead по умолчанию; product_manager с обязательным направлением, product_head с настроенным набором. Soft можно снять явным `product_line=all`; strict возвращает 403 при попытке выйти из набора, включая report T244. Unknown role/run/filter syntax — 422 до запросов данных.
- Nullable деньги и доли при неизвестном покрытии, рядом числитель/знаменатель; никакого вызова compute_incident. Источники — только catalog projection T240; текст маскируется shared privacy helper. Неопределённое направление не выводится из текста/gold.
- SQL proposal: `T-241-ddl-proposal.sql`, пока НЕ migration. Два fact views без размножения; два индекса; nullable actor_role с CHECK семи presets, legacy NULL без backfill. Старый v_cabinet_kpi неизменен (runtime consumers не найдены).
- `actor_role` для новых human_decisions/incident_status_history: header preset при решении/ручном переходе; actor_ref/decided_by остаются исходной меткой сотрудника. Ошибочная роль не приводит к записи. GET отдаёт nullable поле. Это происхождение ручного действия, не утверждение личности. Автоматические действия не получают человеческий preset задним числом.

## Зависимости и временная схема

Normal merge T240 5d128ac, P1 98f57eb и T254 39d21074. API22 зарезервирован root. Фактическая DDL17 ещё не получена: Alembic chain остаётся0014, DDL18 будет только после normal merge реального0017. По отдельному разрешению root targeted PG выполняется на собственной cx_cabinet_revision: upgrade0014 + предложение SQL, без фиктивной Alembic revision. Финальная проверка обязательна повторно на настоящем0018.

## Проверки

Checkpoint: contracts45/paths163; 52 scoped tests (28 pure unit +24 actualPG/API) green15.19s на0014+proposal. Проверены strict/soft, report guard, run isolation, pagination/filters/privacy, nullable saved economics, fanout dedup, actor_role labels и GET fingerprints всех public tables. EXPLAIN ANALYZE aggregate regression без correlated SubPlan; mypy11модулей green. Это provisional setup, не окончательный actual0018 proof. Demo p95/full suite/coverage ещё не выполнены. Никакой полной приёмки не заявлено.

## Фактическая DDL18

После normal merge actual0017 `28c26f8` оформлены canonical/mirror SQL и Alembic0018→0017.
Upgrade18 аддитивный и идемпотентный. Downgrade удаляет только два read-only views и два
индекса, сохраняет actor_role columns/values: происхождение аудита нельзя потерять при
откате кода. Физический drop требует отдельного решения и экспорта. Root согласовал
эту границу rollback. ORM сгенерирован из canonical schema, 110 классов, без ручной правки.

Exact provisional52 at9955a0d отдельно от actual18: 53 tests passed17.07s, fresh18,
два reapply без изменения table fingerprints, actual downgrade17→upgrade18 сохраняет
actor_role. Coverage actual18:200/207 executable lines (97%),53tests55.92s.
Верхняя оценка производительности на demo и full suite остаются отдельным незакрытым этапом.

После bounded config guards:58targeted tests passed16.73s; malformed cabinet visibility/product_head config возвращает409, неизвестный binding422. Ранее coverage97% относится предшествующему source, точные полные проверки следуют после freeze.
