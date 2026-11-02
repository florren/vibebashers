# T-234 — contract-change: полное read-only раскрытие веера

Статус: реализация для ревью; human review техлида по AGENTS.md §7 **ожидается**. До этого contract-change не сливать. Ветка `codex/T-234-trace-graph`, normal-merged с main `f2ac951`. Карточка T-234, ТЗ 28.5–28.7.

## Причина и конкретный diff

Существующий `include=detail` сохраняет свёртку веера: три примера и общий count, before ≤40/after ≤200. Через него невозможно получить все N событий. Его поведение и legacy default `run_id=all` не меняются.

OpenAPI → 1.5.16: добавлен `GET /api/trace/{kind}/{ref}/relations`, где kind/ref — фактический anchor группы. Обязательные direction=`before|after` и event_kind=`signal_created|notification`; limit=1..100 (по умолчанию 50). Новая строгая `trace_relation_page.schema.json`: anchor(kind/ref/event_id), direction, event_kind, total, items (существующие маскированные TraceEvent), edges (реальные связи), next_cursor. В существующей группе TraceResponse добавлены необязательные phase и anchor, только когда assembler действительно знает родителя. Legacy ответ без них валиден; неоднозначный родитель не угадывается.

У **нового** endpoint default `run_id=current`, пустая строка также current; baseline доступен всегда, отсутствующий current не подменяется all. Положительный bigint выбирает запуск, `all` требует явного выбора. UI обязан передавать ровно scope родительского Trace. Это намеренно отличается от legacy default существующего GET Trace. Cursor привязан к каноническому anchor, семейству, направлению и эффективному run scope; смена current между страницами даёт 422. Cursor ASCII ≤1024 байт, строгие ключи/типы/границы, нет интерполяции его содержимого в SQL. До read_db новый endpoint отклоняет isdigit-символы вроде², не принимаемые int(), и числовые PK вне positive bigint; Unicode decimal поддержан, строковые code-ключи не ограничиваются фиктивным bigint. Общий parser/legacy Trace не изменён; empty path остаётся404 без DB, неверный ref —422.

Keyset по PK с upper fence первой страницы не включает поздние INSERT. Count и страница читаются в одной существующей REPEATABLE READ READ ONLY транзакции с statement_timeout. Это **не исторический snapshot между HTTP-запросами**: удаления или изменения связей могут менять total; перечитать группу можно с первой страницы. SQL собирается исключительно из внутреннего RELATIONS/TYPES allowlist, значения параметризованы; count не гидратирует N строк в Python, payload загружает ≤limit+1 объектов. Без DDL, миграций, новых зависимостей, тем WS, записей и LLM.

## Совместимость и порядок интеграции

1.5.16 зарезервирована после T-067 1.5.12/T-091 1.5.13, T-108 1.5.14 и T-040 1.5.15. При normal merge сохранить их диффы (Client360 RunId; compare 3..5000/20RPM/429; audit и lifecycle), разрешив только итоговую версию 1.5.16. Эта ветка стартует от main 8bb7394 (1.5.13), поэтому version jump не означает удаления будущих изменений. TS и Pydantic получены генераторами; ORM/schema.sql не изменены.

Откат: убрать новый route и необязательные metadata/типы вместе с UI; DDL/данные восстанавливать не требуется. Старые trace-клиенты работают прежним способом, однако три sample_refs не следует выдавать за полное раскрытие N.

## Проверка producer

- Post-guard unit/PG: 53 passed (48,82 с). Полный keyset walk 1001 signal +1001 notification, без дублей/пропусков; current/числовой scope/baseline/all/foreign/missing current; cursor family/direction/anchor/scope mismatch; upper fence и пустые группы; ПДн в масках.
- Все public application table count+MD5 fingerprints до/после read-only обхода совпали; Bomb ProviderChain: 0 вызовов. Только выделенная `cx_trace_graph_revision`, синтетические fixture-записи создаются перед read-only проверкой.
- 10001 реальных связей, page50, 10 actual TestClient/PG GET: последний post-guard p95=122,96 мс (<300), payload <100KB, отдельный traced request peak=258387 bytes (<8MiB). Локальное измерение, не гарантия удалённого оборудования.
- Новый fanout.py с bounded ref guard: stdlib sys/threading.settrace, 157/159 executable lines =98,74%; 52 passed, 1 performance case deselected при измерении coverage. Performance измерен отдельно без tracing.
- Соседние Trace/Journey/Terminal регрессии: 56 passed (28,63 с). TypeScript typecheck green.
- contracts_check: 45 схем/162 пути; make sync-contracts; Ruff; mypy 254 source files; final make lint: 188 frontend/Ruff353/drift192 green. Полный make test до bounded ref guard: 1406 backend passed/22 skip +188 frontend; после guard 53 затронутых unit/PG green, без повторения 20-минутного backend suite. UI/24 actual production варианта и оставшиеся gates описаны в T-234-trace-graph-verification.md; этот документ не объявляет T-234 done.

Артефакты локального прогона: `/tmp/vibebashers-t234-fan-final.log`, `/tmp/vibebashers-t234-fan-perf.json`, `/tmp/vibebashers-t234-producer-coverage.json`. Содержимое событий/секреты в отчёты не выводились.
