# T-248: API1.5.28 и actual0020, implementation checkpoint

Это локальный reviewable кандидат, не завершённая карточка и не финальный CI. Исторический storage checkpoint e7e4377 с временным parent0018 сохранён отдельно; текущий0020 имеет actual0019 parent. Полные проверки, final coverage, final performance и human API/DDL review ещё требуются.

## Поведение

CSI GET реализован вместо501. Явные current/all/id, period, branch/region/direction; default current не подмешивает baseline. Shared CabinetScope сохраняет прежний default кабинета; отдельный include_baseline=False используется метриками CSI/ВСП. Presentation role не является RBAC.

Жалобы, таблица, scatter, должности и региональные counts фильтруются по native received_sim. Probabilities используют только полную зарегистрированную когорту того же run/direction/branch и целиком включённое observation window, с integrity digests в том же read-only MVCC snapshot. Response_at и received_sim не смешиваются. Legacy csi_visits_agg не размечается задним числом. Missing/incomplete/partial sample/zero divisor остаются null. Spearman рассчитывается по ordinal buckets и probabilities с tied ranks; n_buckets — число пригодных корзин, не число посетителей и не causal effect. Synthetic/mixed provenance явный.

Таблица limit≤200, offset≤100000; scatter≤5000 с shown/total/has_more. Должности агрегированы; box plot стажа считает каждый active employee один раз на общем as_of, missing/future tenure не равен0. ФИО сотрудников не возвращаются, summary маскируется. Analytics не вызывает модели и не пишет данные. Регистрация корпуса перенесена из analytics в ingest/csi_cohorts.py: только caller-owned TX, native normalizer, явный namespace, без HTTP endpoint или автоматического seed.

Справочник ВСП учитывает тот же strict direction; private TTL86400 и Vary по role/direction. Карточка содержит только явно связанные CSI branch_id/geo.vsp_code сигналы и native CSI metrics, без географических догадок. Динамические метрики карточки не имеют directory TTL. Global history сохраняет старые branch_network_history значения; direction subset имеет отдельный provenance scoped_directory_lifecycle по явным датам snapshot. Неизвестные даты не становятся нулём. Pressure — customer signals/open branches; unknown status/zero open →ratio null. settings.csi_analytics.deficit_signals_per_open_branch должен быть finite positive; отсутствующий порог даёт unknown, выдуманного default нет. Closure zones используют совпадение региона И города, received_sim в [closed,closed+90days), пересечение этого окна с выбранным period. Это per-branch таблица: один город с несколькими закрытыми ВСП не превращает сумму строк в unique total.

DDL0020 additive: три cohort tables, composite FK, immutable snapshots, hash integrity view, scoped audit, без backfill старых визитов. Рекомендуемый rollback кода сохраняет данные. Явный downgrade0020 удаляет только новые tables/view/indexes/functions и требует предварительного backup; production downgrade не выполнялся.

## Проверенные этапы

- После CSI JSON/current scope исправлений:10 native API passed34.61с. Ранее red показал Decimal strings против numeric schema и baseline leakage; исправлены production сериализация и явный scope, asserts не ослаблялись.
- После branch DTO/presets:49 native PG CSI+ВСП+cabinet tests passed152.70с, включая read-only fingerprints, strict foreign rejection, native cohorts и старые кабинетные guards.
- Schema96/upgrade/downgrade/drift и install:15passed55.82с +1 fixture failure из-за dict-row connection в tuple-row baseline API. После исправления test caller: actual dump/restore passed9.79с;10полных когорт/2400визитов и исходные digest/run IDs восстановлены.
- Pure math/scoped corpus/integrity и native parameter bounds:29passed2.65с.
- Первый native demo5000:90 GET /3 routes, первые включены,15 actual plans, fingerprints unchanged; p95 CSI34.575мс /ВСП16.213мс /карточка23.289мс. Proof T-248-initial-performance.json содержит source hashes. После него уточнена closure-window граница; этот benchmark не объявляется final-source измерением.
- Первые два запуска API не прошли setup из-за неверного SQLAlchemy driver DSN и pg_dump18 вместо обязательного16; logs сохранены, это не green и не причина менять guards.

UI T-249/T-250, scenario14/T-262 и replay/live приёмка этим checkpoint не закрываются. Реальные LLM/Telegram/email, рабочая БД и глобальные настройки планировщика не затрагивались.

После обычного merge foundation e347e87 (включая public-run team enrollment95c77 и actual0019): make lint зелёный,367frontend/Ruff507/mypy312/bot12/5/drift195. Полный backend unit:1944passed/18skip70.50с. Первый lint остановился из-за отсутствия локального tgbot/.venv; подключено уже существующее изолированное окружение, без установки dependencies, полный повтор зелёный.

После этого finite-positive threshold guard уточнён для огромных JSON integer (OverflowError→409, без500);4native branch boundary tests passed33.35с покрыли также closed91days: week пересекается с90-day zone, day уже нет; unknown branch status не даёт известного ratio, отсутствующий/неверный directory source/time не становится synthetic/now, directory GET доступен без SimClock. Новых policy defaults нет. Final frozen checks/coverage/performance ещё впереди.
