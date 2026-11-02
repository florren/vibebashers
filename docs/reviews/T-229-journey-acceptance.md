# T-229: три записанных пути и собственная клиентская дорожка

Сценарий12 читает уже записанные native scenario runs через GET. CLI понимает
alias `journey_three_trajectories`; по умолчанию требует настоящий источник
`replay`, `--recording-source live` проверяет ранее записанный live. Команда
не запускает модель, не создаёт signals/runs и не записывает кассеты. Missing
recording, неверный DTO/ref, подмена Mock источником replay и недостающая
траектория дают FAIL. Discovery выполняется в READ ONLY REPEATABLE READ.

## Три траектории

- Автономная: существующий сценарий8, возврат, публичный и личный ответ.
- HITL: вариант сценария1 для ultra_vip с существующим guard; обычный mass-вход
  не обязан требовать человека. Ждём решение, ранней доставки клиенту нет.
- Уточнение: сценарий11, сохранённый вопрос и фактическая публикация, затем
  due followup. Социальный вопрос имеет kind public_reply: цель подтверждается
  native decide и фактом доставки, не угадывается по тексту.

## Изменение эскалации — обязательный human review

Обработчик тишины читал отсутствующий в decision schema `escalate_on_silence`
и игнорировал уже сохранённый план `decision.escalation`. Теперь исполняет этот
план без нового вызова модели. Явный legacy False, прежний fraud fallback и
ветка полученного child reply сохраняются. Severity/to_role берутся из плана;
новых порогов, прав, платежей или финансовых формул нет. Это новая граница
эскалации/HITL по AGENTS.md §5.1: до подтверждения merge не выполнять.

## Клиентская дорожка

Общий incident содержал доставки, посты и реакции других клиентов. Для SIG
дорожка ограничена адресатом и его постами; anonymous delivery — точным
signal_id. Собственный подарок без signal_id виден. Для POST адресат берётся
из нативной связи с signal, не из author hint. При неизвестной/неоднозначной
связи частная доставка не придумывается; публичный ответ самому post виден.
Два дополнительных regression и actual POST GET воспроизвели этот второй вход.
Подробности: T-229-post-source-scope.md. DTO/API/DDL не меняются.

## Проверки

Финальный runtime source `ab9b8daac9d21e156ac583c860f87e7f1dc42a57`:

- 1432 unit passed /18 skipped (40.43s).
- 45 адресных unit/actual PG passed (74.39s): native trajectories/followups,
  Trace/Journey, собственный/чужой recipient, source/ref/privacy negatives.
- 111/115 новых исполняемых строк =96.52%; hashes/сводки в final-coverage JSON.
- Ruff/formatter380, mypy258, frontend lint/typecheck — green.
- Actual production browser:54cases (3paths×3modes×6ru/en/theme/mobile variants),
  плюс6 кадров waiting_human;84table fingerprints неизменны, нет external,
  nonGET, page errors и LLM attempts. SIG/POST содержат одинаковый набор
  сообщений со всеми полями/кратностями. При одинаковом timestamp порядок
  обхода graph не определён; comparator нормирует только порядок.
- 150 actual localhost GET на трёх путях (обычный/presenter), по25 samples:
  худший p95=40.135ms при≤200events;84table fingerprints неизменны. Warm,
  actor-free200client synthetic bank; dedicated resource allocation нет,
  другие isolated test DB работали на том же PostgreSQL host. Это не benchmark
  активного Sim/demo5000. Детали: T-229-http-performance.json.
- Постоянный Playwright:13cases (3paths×ru/en×themes + исходный WS follow),
  5.2s, явно mocked API. Он дополняет, не заменяет actual API/PG proof.
- Main/personal production builds green, генератор карточек идемпотентен.

Полный `make test` стартовал до последнего POST дополнения и завершился:
1430unit/18skip,287integration/2skip,43scenarios/2skip,31compliance,330frontend.
Итого1791backend/22skip и330frontend. Post-fix готовился во время прогона;
эти результаты не выдаются за проверку неизменного финального head. Для него
выше выполнены новый полный unit и адресные actual PG; полный CI обязателен.

Все native graphs имеют явный Mock-provider. Настоящие replay/live recordings
трёх траекторий, финальная demo-композиция, CI/review/merge остаются отдельными
приёмочными условиями; карточка in_progress. Новых внешних вызовов не было.
Own preview остановлен. Скриншоты и raw proof: docs/screenshots/T-229/.

Откат — revert PR; миграций нет. Уже созданные manager escalations автоматически
не удалять. Cross-layer L1/L3/L4/L5 согласован общим поручением пользователя;
отдельное подтверждение эскалации пока не получено.
