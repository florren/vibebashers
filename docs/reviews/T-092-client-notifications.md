# T-092 — уведомления выбранного клиента

Client360 теперь ведёт в `/workspace?tab=notifications&client_id=<id>&run_id=<scope>`.
Используется существующий GET `/api/notifications`; API/DDL и денежные/HITL правила
не меняются. Scope current/all/числовой передаётся из профиля, а не сбрасывается.
Центр уведомлений применяет одновременно client_id/run_id/recipient_type. Кнопка
сброса удаляет только client_id. Это фильтр представления, не аутентификация.

Некорректный, неположительный или unsafe-integer client_id показывает ошибку без
нефильтрованного запроса. Query key включает клиента и запуск; placeholder прежней
выдачи удалён, поэтому при переключении клиента старые сообщения не показываются.
Обычная нефильтрованная вкладка и polling6s сохраняются.

При native браузерной проверке найден соседний дефект: Client360 запрашивал
несуществующий `/api/refs/gift_catalog`, unit/browser fixtures скрывали404.
Профиль использует уже существующий `useGifts()` → GET `/api/settings/gifts`,
DTO и формат названий прежние. PUT, выбор подарков и их стоимость не менялись.

## Проверки

- RED до исправления фильтра:12failed/11passed; отдельный RED каталога:1failed.
- Окончательные focused tests:24passed/2files; полный frontend:574passed/80files.
  ESLint, typecheck и обе production-сборки прошли. Backend/контракты не менялись.
- На собственной disposable PostgreSQL миграции0001→0020, seedlite200 за3.9s.
  Три синтетических обращения двух клиентов в двух запусках созданы через настоящий
  normalizer/Mock AgentService. Human accept и реальные внешние отправки не выполнялись.
- Затем writers остановлены; GET-фаза с APP_ENV=test, загруженным paused Simulator
  и PG default_transaction_read_only=on. SQL-эталон фиксируется после остановки:
  асинхронные native уведомления могли появляться после ответа POST, ранний снимок
  подготовки не использован как окончательный эталон.
- Native Chromium ru/en×light/dark:4/4; переход из профиля, точные API IDs для
  своего/чужого клиента, двух запусков/current/all, recipient filter, clear filter,
  invalid-ID отказ. Бизнес-ответы настоящие; только GET settings.ui переопределён
  для языка/темы/layout fixture. Нет POST/PATCH/внешних запросов в браузерной фазе.
- 97/97 public fingerprints неизменны,8 скриншотов desktop/mobile. После resize
  проверяется устойчивая ширина360 за конечное ожидание1s; мгновенная ширина могла
  быть650/678 во время перестройки, исправлением layout это не объявляется.
- Contracts48/167 и gen_tasks2/idempotence прошли. Owners требует согласованный
  cross-layer для L1 review/screenshots и L5 e2e fixture; --allow-cross прошёл.
- Независимый static review: замечаний нет; это отдельно от root test/browser proof.

[Machine proof](T-092-client-notifications-proof.json) содержит manifests/IDs/хеши.
Скриншоты: `screenshots/T-092/`. Первые неуспешные проверки сохранены локально:
устаревший preparation snapshot, настоящий404 каталога, мгновенная resize-проверка.
Общий exact-head CI ещё обязателен; whole-card T-092 не закрывается автоматически:
приёмка reports_missing на командах этим узким пакетом не повторялась.

Откат — revert frontend-пакета. БД и существующие уведомления не изменяются.
