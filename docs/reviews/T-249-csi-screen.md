# T-249: CSI UI и сохранение выбранного запуска

Страница /csi заменяет placeholder и показывает семь функций FR-8.1–8.7:
таблицу жалоб/IdLink/путь, scatter, должности, custom R7 box plot с наблюдёнными
min/max, вероятности/Spearman, карту регионов и top10 ВСП. Данные берутся из API28;
браузер не считает деньги, знаменатели, квартили или корреляцию. Полные табличные
альтернативы доступны; неизвестное не превращается в0. Synthetic label относится
к зарегистрированной probability sample, не ко всем жалобам. API product_line
остаётся явно cohort_declared/classified/unknown, без подмены классификации.

Run/period/direction/region/branch/offset сохраняются в URL. Query keys включают
scope и preset headers; старый результат запрещённого role не показывается после
переключения. Заголовок направления менеджера не расширяется выбранным фильтром.
Справочник ВСП пагинируется по200, cache24h с ключом headers/scope; выбранный ID
вне загруженной страницы показан явно, а не All. Каталог направлений получен из
существующего read-only cabinet API с теми же headers. UI preset не является RBAC.

## Переход к пути обращения

Найдены две ошибки существующего consumer: Journey игнорировал run_id, а его
GET incident economics запускает пересчёт. Теперь явный scope сохраняется в
follow/replay/presenter, picker, cache keys и переходах. Explicit context только
для просмотра: нет DemoExecution/composer/HITL controls и economic compute GET.
История ожидания/human decision остаётся видна, решения не принимаются.
Без query run_id прежние live composer, HITL и economic behavior сохранены.
Проверены старые ingest retry/idempotency assertions; промежуточный ref-key reset,
ломавший followup state, исправлен до финального прогона.

Пустая строка query раньше опускалась общим qs(): explicit run превращался в
default. Локальный requireRunScope запрещает empty/whitespace до fetch только
в новых CSI/Journey consumers; непустой invalid получает server validation.
Общая сериализация qs и остальные consumers не менялись.

## Проверки

Final435frontend/62files13.35с;57focused были проверены до последнего fallback,
новые fallback и foreign-AR cases вошли в final435. Typecheck/lint/motion и обе production builds
green. Сохранён единственный прежний DemoMenu FastRefresh warning; chunk-size
build warning не подавлялся. Новый frontend не требует зависимостей.

Native production UI:5passed5.5с (ru/en×light/dark и390px mobile),12 screenshots,
без response mocks/CDN и pageerrors. Сравнение таблиц/чисел/ссылок с настоящим API.
Первый browser run4timeouts возник из-за getByLabel с текстами option; независимый
probe доказал accessible combobox name, locator исправлен наgetByRole без изменения
assertions/timeout. Первый full Vitest запуск из неверного cwd дал2CSS ENOENT;
повтор изfrontend прошёл без изменений этих тестов. Ошибочные логи сохранены.

Отдельный actual CSI→Journey→Replay: все97public tables byte-fingerprint unchanged,
все запросы GET/HEAD, внешние запросы блокировались, computed economics GET запрещён.
Proof/source hashes: [JSON](T-249-native-ui-proof.json). Собственная
cx_csi_ui_revision, native seed200 +normalizer300/scoped300members/2400visits,
APP_ENV=test отключает фоновых actors. Глобальный Header SimClock в этом режиме
отвечает503; полноценное runtime/header принятие здесь не заявляется. Никаких
реальных LLM/Telegram/email или рабочих данных. Policy, деньги и Backend не менялись.

[Screenshots](../screenshots/T-249/README.md). Parent #198 обязателен, затем exact-head
CI и обычная композиция main перед merge. Blanket authorization до03.11.2026 07:00
Europe/Moscow ограничено изменениями без деструктивного эффекта; никаких production
операций этим PR не выполняется. DDL/API не меняются. T250/T262/replay-live acceptance
и общий аудит всех карточек остаются отдельными незавершёнными обязательствами.

Дополнительная scoped-AR regression сначала RED: Signal.agent_runs содержал99,
которого нет в выбранном trace; consumer загрузилего. Теперь при explicitrun AR
берутся только из actual scoped trace refs/engine links; legacy list неизменён.
Тот же testGREEN и final435 подтвердили границу; RuntimeAPI/исходная история не
меняются. После этого повторены productionbuild/native5/97fingerprints.
