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

Compact mobile trigger расположен непосредственно в Header, не внутри Drawer:
QR modal не вкладывается во второй modal/focus trap. Desktop сохраняет text button.
После credential binding26backendunit/PG passed26.36s;41bot7.95s;
network-none container smoke прошёл с Python CLI. Полный unit1647 выше относится
к предшествующему checkpoint; final full/backend UI доказательства версионируются отдельно.

## Actual UI proof0708fd9

6production cases: ru/en×light/dark1920×1080, дополнительно ru/light иen/dark320px.
Настоящие health/heartbeat/QR endpoints, read-only synthetic PostgreSQL, browser без
route mocks. Poll proof подписан локальным synthetic service, delivery task —
явный stand-in; настоящего Telegram нет. Cold healtherror/QR503, затем actualHMAC
proof, одинmodal, SVGloaded, Escapeвозвращаетфокус, overflow≤1, mobileHeader≤100px.
94tablehashes до/после совпали,0browsernonGET/0external/0LLM/pageerrors. Guardmarkers
проверены. Исходный UI capture попадал в180ms fade-in; итоговые6PNG пересняты после
штатного завершения finiteanimation и визуально проверены. Process preview остановлен.
Скрипт:frontend/e2e/tgbot-qr-actual-proof.mjs; artifacts:docs/screenshots/T-122/.

Backend coverage новых executable строк84/85=98.82% относительноT1217acce1b;
liveness48/48=100%, middleware2/2, public32/33, health2/2. Hashes и source0708fd9
вT-122-backend-coverage.json. Fullsuite на final composition ещё впереди.
README содержит отдельно обозначенный staticQR бота изТЗCXPulseControlBot и команду
локального экспорта actualQR; статическое изображение не выдаётся за live readiness.

## Финальная composition перед PR

Source0c4eec0:1661unit/18skip49.35s,353frontend+ESLint/typecheck green9.68s,
50bot fake SDK/HTTP/CLI green7.17s. Это последовательно выполненные проверки,
а не полный make test: полный integration/scenario/compliance gate нужен в CI.
После ordinary merge currentparent42907e6/main db1f73c source49f2872:26corpus
regressions green; прежние source-qualified coverage/build/UI artifacts сохранены.
Финальные новые full-suite/CI результаты будут добавлены после их завершения.

Контракт меняется только вперёд: API1.5.23, optional health username + HMAC heartbeat;
нового DDL нет. Требуется final review техлида по AGENTS§7. Оговорка об одобренной
S2S проверке не выдаётся за одобрение конкретного нового heartbeat контракта.


Композиция с T121 b85d377 (main73425): сохранены обе группы locale botQr/shell и compact QR trigger вне mobile Drawer. После merge:361frontend tests, lint/typecheck,50fake bot tests(7.18s) green. Новых Telegram-вызовов нет; full backend проверяется CI текущего head.

Actual production composition proof ed987d5:12 cases legacy/v2×ru/en×themes+mobile320 прошли,94table fingerprints unchanged,0external/nonGET/pageerrors. QR cold503→signed local synthetic heartbeat→200, Escape возвращаетfocus; compact trigger внеDrawer. Evidence:docs/screenshots/T-122/composed-v2/. Первый setup не задавал обязательный public origin, поэтому fail-closed503; повтор с localhost origin прошёл без runtime изменений. No liveTelegram.


## Композиция с актуальным main и исправлением TraceGraph

После CI failure76c1624 (Trace fanout p95 315,50 мс) включён обычным merge mainbe49a8d с PR192. Исправлена production JSON projection, порог300 мс и samples не ослаблены. На source7b54d51:95 unit/actualPG tests passed86,08 с (fanout/plan budget/journey/bot readiness), p95 существующего10k gate15,54 мс; frontend366tests, ESLint/types и backend Ruff/format/mypy/drift зелёные. Evidence: T-122-be49-composition.json. Это локальная проверка композиции; новый exact-head CI обязателен. Ранее согласованный API23/heartbeat/QR контракт не меняется; реальные Telegram вызовы не выполнялись.
