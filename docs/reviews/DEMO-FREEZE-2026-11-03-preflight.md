# CX Pulse Control: проверяемый показ на 5 и 8 минут

Статус: **черновик для review, не результат репетиции**. Разделы T204/T260/T154 не объявляются выполненными. Временные интервалы ниже — бюджет ведущего, а не измеренная задержка системы.

Основа пакета: integration `4107a01396ec8bffccb6746945cf996f9ade894f`, включая T092 `6f0668e63d118108e010b666e2e40a5150d761ac`, preparation follow-up `1fb` и полный synthetic backup/recovery report. Перед репетицией зафиксировать конкретный candidate SHA/image и состояние его exact-head CI. Репетиция проводится **до общего фриза** на неизменном candidate; прошлые отдельные native proofs не заменяют её. Порог report p95 остаётся 300ms: локальная повторная проверка дала 144,5ms, CI207 shard3 зелёный; product fix не выполнялся, добавлены диагностики. Остальные checks и финальный image-smoke проверяются отдельно.

Это минимальный оффлайн показ **новых кабинета/CSI/ВСП и реального текущего графа**. Он не заменяет полную приёмку исходных сценариев 1–15 и прежних блоков A/B/C из ТЗ18. Полные A/B с возвратом комиссии и распознаванием аудио в основной слот не включены. Existing PITCH PR176 не изменён и не считается включённым в release.

## Состав и роли

- Ведущий: показывает UI, произносит ограничения и не принимает решения за сотрудника.
- Оператор подготовки: до выхода создаёт только новые named counters runs на собственном disposable synthetic стенде, сохраняет manifest и проверяет результат. В показе не выполняет SQL, reset, переключение провайдера или repair.
- Основной режим: **effective Mock** для main/fast/twin, видимая метка Mock. Это работающий normalizer/graph/tools на синтетических данных, но не демонстрация качества настоящей LLM.
- Начальный пресет `cx_lead`, направление «Все» для CSI/Map. В кабинете отдельно показать `product_manager` с привязкой `deposits`. Это фильтры представления, не авторизация/RBAC.
- Один язык и тема на основном показе: ru/light для проектора. en/dark — отдельный короткий кадр только после прохождения native matrix, не одновременное переключение четырёх комбинаций в регламенте.

## Подготовка до таймера

### 1. Проверить стенд без изменения рабочего банка

Использовать только собственные project/БД/volume и заранее подготовленный образ финального SHA/API1.5.31/DDL0020. `BASE_URL` — конкретный localhost либо согласованный адрес этой копии. Не направлять команды на пользовательский стенд.

1. GET `/api/health`: HTTP200, БД доступна; GET `/openapi.json`: `info.version=1.5.31`. Отсутствие live provider при явном Mock не маскировать ложным заявлением «LLM live доступна».
2. GET `/api/sim/state`: записать `current_run_id`, `sim_time`, `running`. `running=false` обязателен. Fresh seeded header может быть baseline/completed; искусственно требовать paused от него нельзя. Если чужой run работает — **не останавливать его**, взять другую копию.
3. GET `/api/agent/runs?run_id=<previous>&limit=500`, читать все страницы по `next_cursor`: предыдущие actors не должны оставаться активными. Не считать client_twin/operator агентами из будущей prepared-cohort, но проверка предыдущей активности охватывает все виды.
4. Убедиться в effective Mock всех трёх ролей штатной конфигурацией; endpoint named preparation ниже дополнительно отвергает не-Mock до эффектов. Не менять настройки или роль ради обхода 409. Выключены real Telegram/email/cloud STT; микрофон не используется.
5. Existing lite200 или demo5000 baseline допустимы, но их старые classifications/история обозначаются **synthetic editorial baseline**. Там нет обещания законченной native 14-day истории, артефактов/AR/реального удержания. Старый архив не конвертировать/восстанавливать в процессе подготовки; snapshot должен соответствовать финальной схеме.

### 2. Подготовить CSI, затем кабинет — два разных запуска

В текущем DemoMenu нет кнопок named scenarios34/35. Ctrl+Shift+R **не выдавать за запуск этих кейсов**. Оператор до показа использует существующий API, не новый endpoint.

Первый запрос:

```http
POST /api/scenarios/csi_and_branches/run
Content-Type: application/json

{"label":"Freeze demo: CSI and branches","reset_mode":"counters","seed":42}
```

Ожидается HTTP202, `run.id=C`, `kind=scenario`, `scenario_id=csi_and_branches`, `status=paused`, `reset_mode=counters`; snapshot effective main/fast/twin provider Mock. Сохранить C как выданный ID, не подставлять исторические номера из скриншотов.

- Штатная подготовка проходит реальный XLSX parser → importer → normalizer → scoped membership/visits.
- 301 новых CSI inputs: **300 registered sample rows / 2400 visits** и ещё один явно synthetic сигнал закрытого ВСП, не включённый в cohort. Для него нет выдуманных wait/employee/visits. Unknown denominator не превращается в 1 или 0.
- namespace allocation, XLSX/cohort hashes и повтор в том же run принадлежат штатному producer. Повторный POST создаёт **новый run**, это не retry прежнего run. При частичной ошибке не «лечить» повторным POST/SQL: оператор разбирает сохранённый plan до новой репетиции.
- GET `/api/signals?run_id=C&limit=500`, GET `/api/agent/runs?run_id=C&kind=agent&limit=500`; читать все `next_cursor`. Set source IDs ровно 301 и равен set primary `AR.signal_id`, без дубликатов, foreign, missing, failed или активных (`outcome=null`). `awaiting_human`/`deferred` допустимы; не принимать HITL и не подменять статус.
- Сверить 300/2400 и hashes с native preparation/registration evidence оператора, не выводить знаменатель из количества сигналов. Для прямого UI/API подтверждения используется GET `/api/csi/analytics?run_id=C&period=month&limit=50&scatter_limit=1000` с role `cx_lead`; конкретные поля считать по актуальному DTO, не изобретать `/check` endpoint.
- GET `/api/sim/state` до/после: clock прежний, paused, current=C. Начальная подготовка очереди выполняется **вне таймера выступления**. Existing E2E имеет отдельный preparation bound120s/hook150s; это не обещание измеренного времени этой репетиции и не изменение UI30s/Map3s/API300ms.

Затем второй запрос:

```http
POST /api/scenarios/cabinet_red_words_report/run
Content-Type: application/json

{"label":"Freeze demo: cabinet and red words","reset_mode":"counters","seed":42}
```

Сохранить выданный `run.id=K`. Аналогично проверить paused/effective Mock/неизменность sim_time; source set ровно два входа и два соответствующих primary AR без потерь/failed/активных. Current теперь K, история C сохранена. Вкладки CSI/Map фиксировать **числовым C**, кабинет/путь — **числовым K**. Не переносить current из другой вкладки догадкой.

Входы — точные тексты existing YAML:

1. «Не могу открыть вклад в приложении, ошибка DEP-TIMEOUT-503. Подаю в суд, также обращусь в налоговую. Требую разобраться с открытием вклада.» Это identified red-word/legal случай: реальный **pending HITL**, не исполненный product route. Записать `SIG_LEGAL`, соответствующий `AR_LEGAL` и native pending decision.
2. «Не могу войти в мобильное приложение, ошибка APP-LOGIN-500. Технический сбой, почините доступ к вкладу.» Отдельный ordinary input для фактического product route `deposits`. Записать `SIG_ORDINARY`, AR/incident/tool-call proof. Нельзя подменять им доказательство маршрута первого legal кейса.

Не считать всю T262 успешной: общие mandatory UI/replay критерии остаются `not_verified`, overall `passed=False`, пока не выполнена полная приёмка. Catalog номера этих named cases **34/35**, `tz_number=14/15`; существующие 1..33 сохранены. `ID=14` не означает новый cabinet case.

### 3. Сохранить manifest и подготовить вкладки

Manifest — только безопасные ID/режим/агрегаты, без секретов, raw settings/headers, контактов и содержимого LLM keys:

- final commit/image digest, API version, local base URL, дата репетиции;
- C/K, одинаковый sim_time, seed, effective providers, role/preset/line/period;
- 301/300/2400, exact source/AR set checks, prepared XLSX/cohort hashes;
- выданные SIG/AR/incident/branch PK и client ID только для выбранных synthetic объектов;
- состояние legal pending и обычного product route; unknown/error поля;
- время wall-clock начала/конца каждого блока, measured duration либо `not_measured`;
- ошибки/HTTP request/status и fallback, если были.

Пока writers дренированы, можно снять read-only fingerprints выбранного стенда для QA. Полный backup/recovery проверен отдельно: [114 таблиц / 60 sequences / 4 schemas](FREEZE-2026-11-03-full-db-recovery.md). Его operational quota/channel таблицы были пусты: он не доказывает восстановление outstanding reservations или ambiguous delivery. Не путать этот полный backup с 97 public fingerprints навигационного теста. Создание runs и inputs — отдельная write-preparation фаза; нельзя утверждать «всё демо read-only». В основном показе ниже навигация читает уже записанные объекты. Клики role/theme/filter меняют presentation/local settings и не считаются бизнес-действием.

Подготовленные UI URLs, подставив реальные ID (показать фиксированную числовую область, не подменять её current после переключения):

- `/csi?run_id=C&period=month` — scope не All; role `cx_lead`, product/branch/region фильтры сняты.
- `/workspace?tab=map&run_id=C` — включить «ВСП» одним щелчком; выбрать **7 дней** для `period=week`, не сравнивать с month без оговорки. Для точного сравнения CSI выбрать совместимое окно отдельно. ВСП берутся из справочника; закрытую ветку выбирать по native preparation metadata, не захардкоженному S0016.
- `/cabinet/deposits?run_id=K&period=week` — role `product_manager`, привязка «Моё направление» deposits; реальная `scope.visibility` видна в ответе. Не менять server soft/strict ради показа. URL сам по себе не устанавливает роль.
- `/cabinet/deposits/report?run_id=K&period=week` — отдельная печатная форма/JSON/XLSX, при зелёном неизменном report gate300ms. Print/PDF диалог не включать в короткий слот.
- `/journey/SIG_LEGAL?run_id=K&mode=presenter` и `/trace/signal/SIGNAL_NUMERIC_ID?run_id=K&mode=graph` — подставить фактические ссылки UI. В presenter режиме только история, не LLM replay provider.
- `/workspace?tab=hitl&run_id=K` — очередь для показа границы, **никаких accept/modify/reject/delegate**.
- Дополнительно `/clients/CLIENT_K?run_id=K` → «Уведомления клиента» → `/workspace?tab=notifications&client_id=CLIENT_K&run_id=K`. Только если у выбранного synthetic клиента действительно есть Sent: иначе показать честное empty либо пропустить расширение. T092 сохраняет run и client; clear снимает лишь client, не run.

## Версия 5 минут — минимальный регламент

**0:00–0:30 — рамка и режим.** Уже открыта CSI. Реплика: «Это синтетический банк. Исторический seed — редакционные данные; сейчас покажем новые обращения, прошедшие настоящий граф в оффлайн Mock. Метка режима видна. Часы стоят на паузе, текущий run K; CSI открыт по сохранённому run C».

**0:30–1:30 — CSI с честным знаменателем.** `/csi?run_id=C&period=month`, роль CX lead. Показать жалобы, scatter/корреляцию, sample/coverage и top ВСП. Реплика: «Здесь зарегистрированы 300 наблюдений и 2400 визитов; дополнительное обращение не расширяет известный знаменатель. Корреляция — свойство синтетического набора, не доказанный эффект банка». Не озвучивать конкретный коэффициент, пока он не прочитан в actual response.

**1:30–2:15 — карта и ВСП.** `/workspace?tab=map&run_id=C`, слой ВСП, реальный cluster → список/карточка закрытого ВСП. Реплика: «Тихое N — только непосредственно связанные сигналы этой ветки в выбранном run/окне. Городская зона за 90 дней — другая метрика». Не делать N из city count. В основном показе не открывать Branch Trace: ссылка использует правильный **branch.id**, но generic карточка объекта не равна полноценному адаптеру T233. Доказанный drilldown ниже — native Signal Journey/Trace. Отображаемый branch code сохраняется.

**2:15–3:30 — кабинет и остановка на красных словах.** `/cabinet/deposits?run_id=K&period=week`, переключить/проверить role product_manager и binding deposits. В фильтре «Только красные слова» выбрать SIG_LEGAL. Реплика: «Красные слова детерминированно выделены до LLM. Этот случай не исполняется автоматически — ждёт человека». Показать статус/предложение, не нажимать решение. Снять red-word фильтр, указать отдельный SIG_ORDINARY и фактический route/tool call. Не рисовать стрелку legal→executed deposits.

**3:30–4:15 — отчёт по тому же scope.** Готовая report page K/deposits/week. Показать понятные выводы и кнопку XLSX, не ждать системного Print. Реплика: «Отчёт собран из записанных данных без дополнительного LLM. Денежные значения — расчёт по действующим ставкам и допущениям; неизвестное не ноль и не обещание ROI». Если gate300ms на точном candidate не зелёный — этот блок не готов; использовать заранее экспортированный labelled artifact только как демонстрацию документа, явно сказав, что это файл с указанного run/source, не live ответ.

**4:15–5:00 — путь и итог.** Presenter Journey SIG_LEGAL/K либо native ordinary SIG. Показать фактический шаг, tool result и клиентскую дорожку. Реплика: «След показывает, что уже произошло и чего ещё ждём. Pending не выдаём за решение, Mock не называем реальной LLM. Наша ценность — единый контекст и управляемое действие, а не обещание автономно закрыть всё».

## Версия 8 минут — тот же скелет, без дополнительных обещаний

**0:00–0:40** — рамка/Mock/source/run, как выше.

**0:40–2:00** — CSI: дополнительно открыть таблицу к scatter/boxplot, назвать actual размер sample и unknown, один фильтр ВСП и возврат к исходному scope. Не менять модель/seed.

**2:00–3:10** — Map: cluster с совпадающими координатами → список клавиатурой → карточка/direct N → кратко четыре блока «ВСП vs сигналы». Дефицит при неизвестном threshold показывается unknown, порог не настраивать ради зелёной метки.

**3:10–4:50** — Cabinet: product preset, ordinary route отдельно, red-word pending отдельно, очередь HITL без решения. При наличии готового report показать JSON/XLSX download по тому же K/line/week. Время выгрузки измерять отдельно, не придумывать «мгновенно».

**4:50–6:10** — «Новый сигнал» — только опциональный проверенный на репетиции write-блок. В header открыть modal, канал chat, выбрать фактического synthetic mass клиента из списка, без микрофона/свободных контактов. Вставить ordinary текст из YAML, перед отправкой озвучить: «Сейчас создадим ещё один вход». Нажать один раз, сохранить returned SIG/AR. Показать «Показать путь»/Trace по фактической ссылке. Новый результат может быть in progress/deferred/HITL: не менять status и не обещать завершение за заранее названные секунды. Если новый input ещё не прошёл accepted replay-independent Mock proof финального source, вместо этого открыть уже подготовленный ordinary SIG; прямо сказать «записанный в этом run вход», не изображать новое создание. После write exact cohort=2 больше не утверждать — manifest отметить third input.

**6:10–7:20** — Client360 → «Уведомления клиента» с K/client. Показать реально Sent, mode/provenance и выбранный scope; отсутствие Sent — честное empty. Подарок, задача или сообщение из baseline/чужого run не заменяют Sent этого клиента в K. Не выдавать pending gift за выданный подарок или уведомление. Убрать фильтр по клиенту только явным действием, пояснив изменение выдачи. При отсутствии подходящего cohort заранее заменить этот блок на read-only graph/tool call уже известного AR, без выдуманного сообщения.

**7:20–8:00** — Presenter Journey/Trace и финальные ограничения. Метрики качества модели/реального ROI не объявлять. Вопрос «а что с живыми каналами?» — отдельный ответ ниже, а не неподготовленный внешний вызов.

## Публичные точки STOP и fallback

1. **Legal/red-word pending HITL:** «Нужно решение сотрудника. На этом автоматическая часть останавливается». Не принимать HD, не отправлять объяснение/подарок/возврат ради красивого итога.
2. **Нет данных/unknown:** оставить видимым статус, проверить C/K/role/period. Не переключать All для сокрытия пустой выборки и не подмешивать baseline.
3. **HTTP409 scope/temporal/preparation:** показать сообщение и остановить данный блок. До новой репетиции оператор выясняет конфликт; не сдвигать clock, не reset baseline, не удалять данные и не обходить guard.
4. **HTTP500, request failed, отсутствующий/дублирующийся AR:** этот блок не готов. Сохранить endpoint/status/ID. Никаких retries кнопкой «создать run», fake response или принудительного completed.
5. **UI временно потерял WS, GET здоров:** разрешено обычное обновление страницы с сохранённым URL/числовым scope. Это не restart backend и не смена модели.
6. **Сеть/ключи отсутствуют:** основной сценарий уже явный Mock; внешняя сеть не нужна. Не редактировать `.env`, не запускать install.sh и не переключать live→replay во время выступления. Несовместимый replay hash — честный miss, не rekey; по умолчанию этот путь не показывается.
7. **Report недоступен:** labelled immutable export с source/date/run допускается как резервный документ, не как live успешный GET. Без такого файла блок пропускается с явной оговоркой.
8. **Общий UI/сервер не готов:** только заранее снятые source-labelled PNG/видео/JSON как демонстрационные материалы. Озвучить, что это запись. Не выдавать их за текущую интерактивную систему.

## Что не показываем и не заявляем

- Новую T020 native 14-day историю, реальные исторические closures/artifacts/AR или полный seed native history за90s.
- Fact, empirical retention, причинный uplift/предотвращённые жалобы только от количества Sent, доказанный ROI, реальные bank outcomes. Hazard не умножаем на100, чтобы получить churn risk.
- Refund/gift/HITL accept или изменение денежных ставок/лимитов. Нельзя брать 961/4050 из другого расчёта и объявлять их сохранённым фактом конкретного инцидента.
- Telegram, email наружу, live LLM, облачный STT и микрофон. QR readiness/offline проверка не доказывает доставку реальному боту.
- Replay произвольного свежего seed или новых данных. Presenter Journey «Replay» — проигрывание native записанного read model, не свидетельство cassette provider.
- Прежние красивые «ответ через2–5с», «все9 сценариев OK», cold start/full demo p95 и percent accuracy без exact source/run/denominator evidence.

## Репетиция до общего фриза на фиксированном candidate — ещё НЕ выполнена

1. Указать final SHA/image/API/DB head; никаких параллельных build/bench/actors других пакетов на измеряемом стенде.
2. Подготовить C/K штатно, сохранить ID/hash/drain manifest. Открыть все URL и проверить без 404/500/внешних вызовов; после T092 старый gift_catalog404 не должен появиться.
3. Пройти 5-min версию один раз с wall-clock таймером. Записать фактическое начало/конец каждого блока, ошибки/ожидание. Затем 8-min версию — отдельно; пока все duration поля `not_measured`.
4. Read-only фаза: QA fingerprints до/после; optional новый сигнал из 8-min — отдельная ожидаемая write-фаза, не включать её в обещание неизменности.
5. Приложить screenshot темы/языка, safe HAR/console diagnostics, HTTP exports с run/source, сохранённые mode badges. Не хранить токены/ПДн.
6. При отклонении более1мин сократить рассказ/опциональные кадры, а не ослаблять timeout/порог или скрывать pending. Финальный фактический тайминг review — prerequisite T204; T260/PITCH обновляются только после принятия этого конкретного сценария.

## Сверка существующих документов: что позднее исправить отдельным docs diff

- DEMO-SCRIPT.md предлагает reset baseline перед каждым блоком и несуществующее обещание «все9 OK»; для этого freeze-показа заменить на named counters preparation вне таймера. Скрытое меню сейчас не запускает новые34/35.
- DEMO-SCRIPT.md советует restart после изменения `.env`; DEMO.md уже верно различает restart и recreate. Новый показ вообще не меняет provider/env во время выступления.
- DEMO.md/DEMO-SCRIPT.md опираются на8/9/10 и E/F как будущие функции. Это исторический script, не сертификат нового CSI/cabinet; сохранить provenance и явно назвать новый отдельный вариант.
- PITCH PR176 содержит полезные оговорки о метриках/экономике. Переносить только проверяемые тезисы, не утверждать, что сам PR уже в integration или что полный A/B пройден этим показом.

Проверенные источники (пути относительно корня репозитория): docs/TZ.md §§4.6,5.4,12.7,18,24,25,27,28; AGENTS.md правила13–20; data/scenarios/cabinet_red_words_report.yaml и csi_and_branches.yaml; frontend/src/app/App.tsx; CabinetPage/ReportPage/CsiPage/MapTab/Client360Page/NotificationsTab; widgets/DemoMenu/JuryModal; backend/app/api/scenarios.py и app/sim/scenario_acceptance.py. Исполнять действия в ходе подготовки этого черновика не требовалось: actors/SQL/frontend/внешние сервисы не запускались.
