# T-122: readiness и QR — checkpoint перед final review

API1.5.23 после резервов19–22, без новых DDL. Сервис-to-service HMAC exception
ранее разрешён пользователем; этот final contract ещё не reviewed. Реальных
Telegram/getMe/getUpdates/sendMessage вызовов во время работы агента не было.

## Причина и поведение

Раньше health считал token доказательством running, QR всегда кодировал
CXPulseControlBot независимо от реального token. Теперь running требует:
полную enabled transport configuration, живой owned delivery task и свежий
подписанный proof успешного polling. Public optional tgbot_username возвращается
только при running. Existing enum running/disabled/error сохранён.

POST /api/internal/tgbot/heartbeat несёт bot_id, username и writeOnly credential_ref.
HMAC exact body/method/path/timestamp проверяется тем же bounded middleware до
обработчика; подпись inbound не работает для heartbeat. credential_ref =
HMAC-SHA256(internal_secret, ASCII `cx-tgbot-credential-v1:` + UTF8 token): raw token
в body отсутствует. Он блокирует heartbeat старого процесса после ротации token
даже при том же bot_id. Digest не публикуется в health/QR, не хранится в БД.

Сервис получает username через actual aiogram getMe при запуске, проверяет
bot ID/is_bot и лишь после successful getUpdates передаёт proof. Backend не
вызывает Telegram из health/QR. Изменение username у BotFather требует restart.
Неуспешный receipt не продвигает update offset; permanent4xx останавливает bot,
5xx/network/429 повторяются с прежним offset, без ack необработанных updates.

Proof живёт90реальных секунд по monotonic clock, без sim-time catch-up. Он
намеренно ephemeral: backend restart даёт error до нового proof, DB migration
и откат банковского baseline ему не нужны. Это operational readiness, а не
подтверждение доставки уведомления. Worker failure/stale/rotation/config error
скрывают username и QR. Смена любых transport settings инвалидирует старый proof.

GET QR:404 disabled,503 enabled-but-unready,200 SVG только для проверенного username.
LRU кэширует SVG payload по username, Cache-Control:no-store не кэширует readiness.
UI hidden при disabled/error/missing username/fetch error, modal480px ru/en,
image failure показывает локализованную ошибку. UI не обращается к t.me/CDN.

## Rollout / rollback

Bot и backend обновляются парой: старый bot не посылает proof новому backend,
новый bot на старом backend получает404 и завершает polling без продвижения offset.
Если требуется rollback, выключить profile/flag, вернуть совместимую пару;
не объявлять ready вручную по наличию token. Никаких новых user roles/auth/RBAC,
HITL callbacks или денежных решений эта карточка не добавляет.

## Проверки checkpoint

- Первый fullunit checkpoint:1647pass/18skip56.77s; это до добавления credential_ref.
- После credential binding:25backend liveness/middleware/actual-ASGI tests3.35s,
 41bot fake SDK/HTTP/CLI tests7.95s, в том числе actual aiogram GetMe/GetUpdates,
 identity rejection, empty poll, backend retry/offset, session cleanup.
- Actual PostgreSQL public scenario1pass8.36s до credential_ref; final повтор/coverage
 выполняется отдельно. Исходные legacy200/SVG/secret-negative assertions сохранены,
 добавлены503 до proof и после остановки worker.
- Полный frontend336tests+ESLint/typecheck и make lint green: Ruff434/mypy284,
 botRuff12/mypy5, drift193; contracts45/163. Обе production builds прошли.
- Preliminary liveness coverage41/43=95%; final source/changed-line coverage впереди.

Final-head fullbackend, screenshots, contractreview, CI и merge ещё не заявлены.
1080p projector на5м и настоящий Telegram jury сценарий остаются ручными критериями;
fake SDK, image build и UI screenshots не подтверждают их. Live запросы требуют
отдельного разрешения и здесь не выполняются.
