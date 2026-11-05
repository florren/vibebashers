# Проверки и обязательные gates перед freeze 05.11.2026 06:00 МСК

## Область готовности

Срез доказательств: 05.11.2026 00:04 UTC (03:04 МСК). Это историческая
запись проверки; актуальные результаты полного v3, CI и rollout указаны в PR #221.

Это проверка реализованного демонстрационного среза и исправлений PR #221,
а не заявление о выполнении всех карточек или покрытии всех возможных путей.
Кодовый source: `173c4c156d1b3653f66825475edfe97190d34d0f`.
Финальные изменения этого отчёта — только документация; merge допускается
только после зелёного CI текущего HEAD PR.

Полный локальный `make test` v3 — отдельный обязательный gate перед merge.
Этот документ фиксирует уже завершённые проверки по стадиям; он не объявляет
повторный полный прогон успешным заранее. Итоговый exit code и результат v3
фиксируются в [PR #221](https://github.com/florren/vibebashers/pull/221).
CI кодового source `173c4c1`: **PASS**, [run 41926519788](https://github.com/florren/vibebashers/actions/runs/41926519788):
3397 backend passed, 24 skipped, 0 failed/0 errors. Exact union всех 4 manifest
содержит все 3421 nodeid без отсутствующих или повторных записей
(из них 24 skipped); штатный verifier прошёл.
Checkout — synthetic merge ad8775c с проверенными parents main `52fd498` / head `173c4c1`.
Bot 50 проходит в lint job, frontend 607 — в собственном job. Все обязательные
jobs, owners, build и e2e зелёные; nightly PR job пропущен по условию workflow.
После добавления этого документа CI текущего HEAD также обязателен перед merge.

## Исправления и согласования

- API 1.5.32: Fact и настоящий XLSX читают сохранённые оценки, соблюдают
  current/all/id, сохраняют unknown/null; частичные неподдерживаемые фильтры — 422.
- Настроенная финансовая доля 0 больше не заменяется ненулевым fallback.
  Это меняет ошибочный пример 2025 ₽ на 0 ₽; ненулевые ставки и выплаты прежние.
- Единственное владение продолжением AgentRun, atomic claim/first checkpoint,
  scheduled busy timer и recovery после durable human entry.
- Начатый COMMIT tick защищён от caller cancellation до определённого результата;
  после успешной фиксации время/RNG в памяти не откатываются к старому состоянию.
- Повторная cancellation не обрывает terminal unknown bookkeeping после Ticket.
  Ранее утверждённые unknown/fail-closed, caps и reconciliation сохранены.
- Exact Nemotron/OpenRouter получает поддерживаемый json_object, полную schema
  в prompt и локальную валидацию; unknown не вызывает повторный inference.
- Настоящая кассета сценария 11, bounded recorder/cold OAuth и DemoMenu 34/35.

Пользователь подтвердил API/денежный zero diff, HITL ownership и tick COMMIT
с условием успешного CI. Terminal bookkeeping исправляет исполнение ранее
утверждённой политики PR #188/#218; конкретное новое human approval ему не
приписывается. Пользователь поручил завершить работу автономно.
DDL в этом пакете нет. Суммы прошлой истории автоматически не пересчитываются.

## Проверки

Подтверждённые source-qualified стадии на `173c4c1` (v2 и отдельный исправленный
bot target; это не объявляется одним успешным полным make):

- Backend unit: 2349 passed, 19 skipped, 68.72s. Skips — 19 schemas без examples.
- Integration: 977 passed, 0 skipped, 4523.48s.
- Scenarios: 44 passed, 1 skipped, 227.22s; live Giga latency намеренно без ключа.
- Compliance: 31 passed, 103.46s.
- Frontend: 607 passed, 83 files.
- Bot: 50 passed, 6.87s с явным source path текущего checkout.

В CI четыре дополнительных skip относятся к отсутствующим frontend/dist,
модели/sample WAV; локальные стадии с собранными assets и Vosk их выполнили.
CI и локальные totals не складываются: это повторные выполнения тех же cases.

Предыдущий полный v2 завершился FAIL на bot stage: переиспользованный venv
импортировал старый cx_tgbot из другого checkout (7 failed/43 passed). Это не
скрывается как PASS. После явного PYTHONPATH текущего tgbot source target прошёл
50/50; v3 driver проверяет происхождение app и bot modules перед запуском.
Все 9 проверенных import paths принадлежат его эксклюзивному checkout; общий
editable venv не перенастраивался. Результат v2 остаётся FAIL.
Production-код и assertions ради этого не изменялись.

`make lint`, contracts check, проверка drift и owners L1–L5 с разрешённым
cross-layer прошли. Исправленный модуль synthetic_ingest прошёл 16 native PG
тестов. Ранее единственный красный тест использовал ручной deferred AgentRun без
followup_monitor и подменял прежний resume entrypoint. Теперь fixture создаёт два
штатных native Mock checkpoint, проверяет настоящий шаг продолжения и сохранение
legacy timer; production-условия ради теста не менялись.

Browser/performance: 168 passed (150 + 13 + 5), seed 27.382 s,
максимальный API p95 71.84 ms, violations=0. Эти 168 browser/performance cases
выполнены на `14a620f` / image `ada81325…`. До `bf01307` единственное runtime изменение —
accounting.py; frontend/API/contracts/data/scripts source не менялся. Свежий
CI nightly на `bf01307` также прошёл, но ему не приписывается прежнее performance
измерение. От `bf01307` до `173c4c1` изменён только test_synthetic_ingest.py.

Для проверок использован pinned image
`sha256:7eb42f2b0966c166c15b77855965bb04b6684ec623f5f82bd79bbf7ac0123f06`.
Его provenance — bf01307, не 173c4c1. Сопоставлены 350 app, 95 contracts,
148 data и 61 scripts files; data/models/stt/README.md явно исключён из сравнения.
Новые тесты выполняются из checkout `173c4c1`.
Отдельные component/CSS screenshot cases включают ru/en, обе темы,
320/1440 px и плотности; это не 168 native acceptance cases.
component fixtures не подменяют native API/scenario acceptance.

Адресные native проверки: 63 continuation, набор 9 COMMIT boundary и расширенный набор 42 recovery/control (не суммируются),
58 terminal accounting. Покрытие изменённых executable statements соответственно
35/38 (92.11%), 11/12 (91.67%), 24/24 (100%). Это не branch coverage и не процент
готовности всего проекта. Детали и rollback находятся в отдельных review рядом.

В runtime log audit browser-набора нет PG ERROR, UNIQUE violation или
StaleSimulatorError. При этом был один agent_node_failed SIG2831:
notify_client effect_time_fence / stale native fault scope. Класс соответствует
предусмотренной отрицательной регрессии fail-closed; точная fault row и rollback
этого конкретного SIG после удаления QA БД не восстановлены. «Все graph runs
успешны» и «нулевые application errors» здесь не утверждаются.

## Live, хронология и внешние зависимости

Штатные GigaChat роли: normalize Lightning, classify/decide Ultra — три успешных
узла, 10158 known tokens. В ограниченном синтетическом прогоне causal chronology
inversions=0, уведомления ack_received/team_notice sent, refunds=0.
ClientTwin live не проверен. Настоящая кассета 11 отдельно прошла strict replay
без HTTP/fallback; изменённый контекст вызывает miss, а не выдуманный ответ.

OpenRouter fast graph и native benchmark **не прошли** штатные 10/30 s timeout.
Провайдер позднее завершил generation; это не успешный прикладной ответ в срок
и не доказательство accuracy. По Management API выполнен штатный operator
reconciliation: confirmed 7463 native tokens, daily key 11/profile 7 на 04.11 UTC,
reserved/unknown 0. Confirmed usage вырос 3795→7463, daily counters не
уменьшены и не сброшены; банковские данные сохранены. Никакого
обнуления или увеличения timeout ради PASS. Studio/открытый браузер приложению
не нужны. Новые реальные inference после исчерпания согласованных планов не
выполнялись.

Хронология проверена на конкретных native сценариях и регрессиях собственных run,
в том числе recovery/concurrency; математическое доказательство всех путей не
заявляется. Старая история с известными timestamp инверсиями не переписывалась.
Физический микрофон проверен пользователем: текст появился в черновике без
автоматической отправки. WAV→Vosk проверен отдельно.

## Rollout и сохранность

После merge выполняется отдельный guarded rollout backend/personal на
пользовательский стенд localhost:9999. До его выполнения этот отчёт не является
подтверждением обновления стенда. Rollout предусматривает fresh full PostgreSQL backup, приватные
копии env, pin прежнего image, FF sync двух main checkout и code-only rollback.
Сверка охватывает 113 таблиц и 59 business sequences, clocks/RNG, checkpoints,
ledger/reconciliations и critical config. Допустимые startup metadata исключены
явно; business history не исключается ради прохождения проверки.

Пользовательские .env/.env.example сохраняются побайтово, .env получает 0600.
Seed/reset, автоматический restore истории, новые inference и запуск Telegram
worker в rollout не входят. Quiet preflight не заменяет held maintenance lease:
неожиданная конкурентная запись вызывает отказ, code rollback её не отменяет.

## Остаточные ограничения

- Раннее сохранение human decision до первого durable entry требует operator
  recovery; после durable entry recovery проверен.
- Потерянный COMMIT ACK остаётся отдельной неизвестной границей. Shield относится
  к tick COMMIT, не ко всем control/baseline transactions; WS publication после
  durable tick не гарантирована exactly-once.
- Terminal grace 3s — мягкий DB timeout, не гарантия elapsed≤33s. Crash, потерянный
  ACK или отказ БД могут оставить orphan; он блокирует вызовы до operator review.
- T-020, T-162/T-164/T-165 и полный T-166 scope остаются deferred. Два прежних 501
  scaffold endpoint не объявлены реализованными. Не все menu native acceptance
  соответствуют полному каталогу сценариев.
- Telegram worker выключен; прежние разрешённые доставки не доказывают все
  входящие пути. SMTP проверен локальным sink, не внешним почтовым сервером.
- PR #176 остаётся business review: сторонние согласования и ручная репетиция
  5/8 минут не подменяются техническими тестами и не закрываются автоматически.
