# T-250 — итоговый кандидат слоя ВСП

Дата: 2026-11-03. Проверенный runtime/source: `d1fc9b191958e00fc9e3df0cb1297bd9d13beda5`.
Этот отчёт и приложенные артефакты добавляются отдельным docs-only коммитом.
Статус карточки остаётся `in_progress`: нужны CI точного публикуемого head и финальное review API30.

## Изменение и совместимость

Слой ВСП использует реальные координаты справочника, кластеризацию, клавиатурный список,
карточку и четыре блока аналитики. Направление менеджера применяется сервером;
пользовательский фильтр не считается RBAC. Для закрытого ВСП N берётся только из
`BranchDetail.signals.total` при том же scope; ошибка/неполученный detail дают unknown.
City90-day статистика показывается отдельно и не подменяет прямые связи.
Запросы закрытых ВСП ограничены тремя фоновыми и одним выбранным detail.

Operational Map задаёт URL `run_id=current` до монтирования Workspace/KPI; остальные
вкладки сохраняют прежние defaults. Явный All сохраняет историю; current без текущего
запуска даёт пустой результат, malformed/empty — 422. Backend omitted-семантика current
сохранена. Map-only SQL одинаково ограничивает сигналы, инциденты и audio alert CTE;
средний legacy churn берётся из клиентов именно отфильтрованных сигналов, без новой
формулы hazard→risk. Глобальный resolver, пороги и финансовые правила не изменены.

API30 документирует RunId для heat/cities и оба семейства уже поддержанных aliases:
`incidents`/`incidents_open`, `churn`/`churn_risk`; неизвестный layer даёт 422.
Сохранены все 179 схем композиции API28/29 и additive поля родителей. Новых DDL/dependencies нет.
Runtime OpenAPI читает canonical version через включённый parent PR204: образ реально сообщает 1.5.30.

Trace ссылки используют выданный PK (`branch.id`/`row.branch_id`), отображаемый code
и runquery сохранены. Реальная коллизия code0042/id1 с другим PK42 покрыта unit и PG:
GET по id1 возвращает VSP-0042, GET `/0042` сохраняет прежний lookup priority и возвращает другой ВСП.
Backend lookup не менялся. Согласованное уточнение `{id}` внесено в generator карточки.

## Проверки и источники

- На d1fc: `make lint` GREEN, 513 frontend tests/74 files, backend mypy326,
  bot format12/mypy5, drift196/196; обе production сборки GREEN. Генерация дважды
  идемпотентна (113 ORM), E2E typecheck с DOM.Iterable GREEN.
- Map targeted28 GREEN. Numeric Trace PG + runtime metadata units:9 passed9.62s.
  Ранние scope/alias PG6 GREEN относятся к 731af/0387; strict map-layout20/20
  относится к f98ac (слой ВСП выключен). Это не полный backend suite d1fc.
- Demo5000:600000 операций/41 fault/240 ВСП, штатные XLSX301→300 scoped members/2400 visits.
  Новый production UI на d1fc: native4/4 ru/en×light/dark; initial290–353ms,
  все branch reads702–747ms. 97 public fingerprints неизменны, ошибок/внешних вызовов/записей нет.
  [Машинный отчёт](T-250-trace-native-proof.json), PNG: `../screenshots/T-250/trace-native/`.
- Новый isolated image `sha256:c56fe472f1d9b9520bf86436c6d79c2054a5e3a8a6585927dc3c3ea292ceb8ff`
  собран из d1fc. Fresh lite200 header baseline/completed, clock stopped.
  Portable4/4 за49.24s с подготовкой, без retries/skips/flaky. Затем native4/4:
  initial289–318ms, все branch reads723–757ms; 97 public fingerprints неизменны.
  [Полный proof](T-250-image-final-proof.json), PNG: `../screenshots/T-250/image-final/`.
  PNG четырёх сочетаний и карточек просмотрены: count glyph ниже anchor, нейтральный
  круг прозрачен, карточка не обрезает подписи. Координаты/touch area/aria не менялись.

Подготовка E2E разрешена только при `E2E_ISOLATED_SCENARIOS` и localhost ownership,
serial settings project после read-only workers. Штатный named counters run сохраняет
историю, проверяет effective Mock и отсутствие активных предыдущих AR, не принимает HITL.
301 source IDs точно равны distinct primary kind=agent AR.signal_id:301 received events,
301 primary AR, active0/failed0, все outcomes non-null. Clock до/после подготовки равен.
Только новая фаза подготовки ограничена60s/hook75s; UI30s/Map3s/API300ms guards не ослаблены.
Business API native; `/api/settings` в UI заменён только для темы/layout. STT requests пусты,
микрофон/LLM live/Telegram/email не использовались. Actors образа реальные, provider Mock.
Fingerprints относятся к 97 public таблицам, не ко всем private operational namespaces.
Собственный image project/PG/volumes/network удалён штатным cleanup; рабочий latest не менялся.

## Ограничения и rollback

Исторические RED/неполные попытки сохранены в candidate review и отдельных JSON;
первоначальный ProtocolNoData не объявляется доказанной исключительно UI race.
Новая успешная проверка относится к d1fc, а старый b98 proof — только к своему source.
Полный backend regression/required CI точного final head ещё обязателен до merge.
Ненастроенный серверный deficit threshold остаётся unknown, не выдумывается клиентом.
APP_ENV=test readiness Header503 исторической host fixture не является proof production health;
новый изолированный image APP_ENV=dev прошёл штатную readiness/actor подготовку.

Rollback: обычный revert согласованного T250 change set; миграций/конверсий данных нет.
API aliases и прежние backend defaults сохраняются. Нельзя очищать пользовательские
данные/сбрасывать baseline ради отката UI. Финальная публикация и merge выполняются root
после проверки этого конкретного контракта и успешного CI.
