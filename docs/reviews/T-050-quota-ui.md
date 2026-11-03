# T-050: truthful operational quota UI — checkpoint

Frontend follow-up от API21 beac5e9; сам financial policy пользователя ещё не
reviewed. Платных/реальных API запросов не было. Backend/контракты/лимиты не меняются.

KeysPanel показывает Unknown при usage_known!==true или requests_known!==true;
старый сервер без flags не превращает неопределённость в0. Подтверждённый
observed_tokens_floor и legacy hint (explicitly unverified) различаются. Остатки
только из tokens_remaining/requests_remaining и только при known; hint arithmetic
удалена. Null limit/remaining не выдаётся за0. UTC requests_day отдельно от sim time,
usage_as_of через существующий formatter реального времени. Balance0USD сохранён.
Raw usage_source и private поля/credential UID не рендерятся.

В двух BenchTab key cards также убран ложный fallback0. Forecast/схема/кнопки запуска
не редактировались; они остаются server-policy boundary. В старом binding fixture
сохранён assert Remaining80 с explicit validated server metadata вместо arithmetic.

Проверки на начальном source:24target frontend (5quota,10binding,9bench) green3.47s,
полный330frontend+lint/typecheck green10.70s. Это до final backend-parent composition.
После обычной composition backend79bb448 + frontend9daea7d: source9e8ed4e,
354 frontend tests + ESLint/motion + tsc green; production main/personal builds green.
4actual production ru/en×themes cases1920×1080: legacy17=Unknown, confirmed0=0,
confirmed123/4, incomplete floor5 + one cancelled synthetic reservation. Fixture
подготовлен только в собственной cx_quota_ui_revision через canonical key API и
accounting reconcile/admit/unknown; реального provider HTTP не было. Это специально
заданные synthetic observations, а не статистика живого провайдера.
101public/channel_runtime/langgraph/llm_runtime table fingerprints неизменны,
0page errors/failed responses/browser external/nonGET. Backend DNS/socket guard и
LLM bomb не сработали. SQL connection допускает legacy SELECT FOR UPDATE; SQL
read-only не заявляется. Screenshots и source-qualified hashes: screenshots/T-050/.
Русская широкая таблица сохраняет штатную горизонтальную прокрутку.
CI и финансовое review всего P2 остаются отдельно; этот UI checkpoint их не заменяет.
