# T-229: три записанных пути и граница клиентской дорожки

Read-only сценарий12 теперь читает уже записанные native scenario runs, имеет
совместимый alias journey_three_trajectories и GET checker. Не создаёт signals,
agent runs или кассеты. По умолчанию требуется replay; --recording-source live
проверяет ранее записанный live, не вызывает модель. Mock в production CLI
не проходит. Проверяются DTO, конкретный signal ref/run, восемь стадий,
возврат/публичный и личный ответ, ожидание HITL без ранней доставки, уточнение
с фактом публикации и эскалация. Социальное уточнение имеет public_reply kind;
его цель подтверждается native decide, не выдумывается из текста.

Демонстрация HITL использует вариант сценария1 с настоящим ultra_vip guard.
Обычный mass-вход сценария1 не обязан требовать человека; его policy не меняется.
Сценарий11 сначала ждёт клиента: для второй части нужен native due followup.
Новый regression показал, что после тишины checkpoint игнорировал сохранённое
решение escalation и читал несуществующий в schema escalate_on_silence.
Исправление исполняет существующий план без нового вызова модели; явныйFalse
сохраняется, прежний fraud fallback сохраняется, child reply branch не меняется.
Это изменение эскалации/HITL требует отдельного human review до merge.

Другая воспроизведённая ошибка: общий incident добавлял в client lane доставки,
посты и реакции других клиентов. Для signal subject дорожка теперь фильтруется
по client_id/собственным posts, а anonymous delivery — по точному signal_id.
Подарок своему клиенту без signal_id остаётся видимым. Общая bank lane/Trace
сохраняет остальные события; DTO/API/DDL не меняются.

До исправления actual native proof:1/3paths passed; после чтения correct
social purpose и native due followup оставалась missing escalation (regression).
Focused graph fix:8PG passed36.77s. Расширенная версия:34passed43.03s; следующий
checkpoint36passed51.05s до финальной заморозки scope. Отдельные regressions
показали чужую delivery и чужой post/reaction; после scopefix7unit passed.
Это история источников, не заявление финального полного suite/coverage.

make lint checkpoint:330frontend tests, Ruff/formatter380,mypy258,drift192/192.
После последнего read-only scope изменение требует финальных backend checks.
Три пути создаются native graph с явно Mock-provider; это НЕ настоящие кассеты.
Live/replay recording, actual browser/performance, полный suite/CI/merge пока
не заявляются. Внешних LLM/Telegram вызовов нет. Рабочая БД не используется.

Откат — revert PR; миграций нет. Уже созданные manager escalations не удалять
автоматически. Финансовые формулы/лимиты/refund rules не меняются.
