# Журнал изменений пакета документации и контрактов

## 01.11.2026 — независимые исходы публичного демо и восстановление (#144)

Публичный чат :9999 получает собственный paused live-run и сохранённый цикл четырёх
исходов на новые инциденты; recovered доступен только дополнительной попыткой после неудачи; связанные сигналы одной проблемы не сдвигают цикл.
Настройки и часы Journey не управляют публичным показом. Для неудачного ручного
инцидента добавлено явное продолжение после эскалации: тот же инцидент, исходный
граф и история, затем релиз, проверка и конечное сообщение. OpenAPI 1.5.11.

## 01.11.2026 — неудачная попытка на паузе и черновик профиля (#142)

Ручная команда эскалирует неудачный фикс через допустимый возврат в работу,
без зависимости от общего SLA-тика. Клиент получает извинение, сообщение о
дополнительном времени и продолжении работ; инцидент не закрывается.
Выбор исхода явно помечен как черновик до сохранения профиля. Сохранённое состояние
синхронизируется с сервером, старые планы не переписываются, явное сохранение
очищает прежнюю ошибку исполнения без запуска часов.

## 01.11.2026 — проверка команды до конечного ответа (#140)

Агент не закрывает активный план команды по одному устранённому fault: ждёт её
проверки и закрытия без ложного reopen. Исторический release-only итог выражается
клиентским языком после проверки verified. APP-CRASH-PAY не наследуется ошибкой503
открытия вклада по одному слову «приложение».

## 31.10.2026 — клиентский итог вместо внутреннего отчёта (#137)

Ручные и публичные обращения получают понятный ответ об устранении, опоздании или
продолжении работы. Внутренние отчёты и source/demo остаются в аудите. Бонус в итоге
описывается по факту выдачи; предложение с pending HITL не считается начислением.
Основной close и ускоренный исполнитель используют общий клиентский формат ru/en.

## 31.10.2026 — ручной сотрудник при ошибке фонового контура (#138)

Отдельно включённое ручное ускорение продолжает сотрудника и команду на паузе даже
при error общего исполнения. Ошибка сохраняется для оператора. Закрытие инцидента
завершает исходный граф по локальному времени; адресное пробуждение не двигает
чужие followup и ожидание ответа клиента. Stop и выключенные режимы соблюдаются.
Связанные HITL общего инцидента обрабатываются тем же сотрудником; checkpoint
блокирующей эскалации продолжается, сохранённое решение восстанавливается.
Промпт demo-role-v3 различает текущую проверку HITL и отдельные согласования подарков.

## 31.10.2026 — первичный seed после bootstrap backend (#135)

- `--if-needed` разрешает первичный seed при одной служебной строке `sim_state`.
- Неполный банк с клиентами/запусками остаётся защищён от автоматической перегенерации.
- PostgreSQL-регрессия проверяет чистую схему, startup backend, seed42 и новые операции,
  сигналы и события активного запуска, отдельно от исторического baseline.

## 31.10.2026 — передача команде после HITL (#133)

Анонимный инцидент после явного accept/modify возвращается из awaiting_human в routed.
При другом нерешённом HITL ожидание сохраняется; reject/delegate не снимают блокировку.
Переход выполняется штатным инструментом с историей, без изменения денежных политик.

## 31.10.2026 — непрерывность ручных обращений (#127–129)

- Ускоренный профиль `/journey` выполняет ручные цепочки при паузе банка на отдельном сохранённом событийном времени.
- Пояснения и названия кнопок отделяют новый сценарий от сохранения профиля; добавлен переключатель ускорения.
- Подбор инцидента использует классификацию текущего сообщения; разные ошибки одного клиента не объединяются по общему типу.
- Регрессии проверяют историю, отдельные SIG, общий инцидент и итог каждого сигнала без повторных действий.


## 31.10.2026 — живые demo-прогоны (#122)

- Исправлены утечка mock-подсказки в live, неизвестные коды ошибок, ложный finished и неполный цикл информационных запросов в demo.
- Уточнены текущие факты команд и итоговые ответы; добавлены v2-промпты и воспроизводимая живая проверка на изолированной базе.
- Пороговый комплаенс-алерт соответствует контракту события (`counter`).

## 31.10.2026 — холодный GigaChat и транспортная ротация

- Зависший TCP/TLS больше не расходует весь бюджет модели: connect timeout 2 с и ротация ключей при timeout/network, в том числе при отмене активного HTTP внешним дедлайном.
- Транспортная пауза мягкая, не обнуляет квоту и не удаляет валидный OAuth; 429/auth/quota сохраняют штатные ограничения.
- Подготовка OAuth/API выполняется до готовности backend (до 12 с, без генерации); keep-alive 60 с. OAuth внутри запроса, ротация и repair делят общий дедлайн модели.
- Benchmark поддерживает `--cold-each --prepare`: время подготовки и полное время холодного запуска сохранены отдельно, без скрытого прогрева.

## 31.10.2026 — резерв Pro для нормализации

- Порядок настроенных GigaChat: Lightning → Pro → Ultra; общий дедлайн 10 секунд, резерв 4/3/3 с. Основная роль Ultra и роль двойников не меняются.
- Детерминированные регрессии порядка, остановки после успеха, ошибок аккаунта и общего дедлайна. Live-набор: 19/20, первый запрос из нового процесса превысил дедлайн; ограничение явно сохранено в отчёте.

## 30.10.2026 — T-267: сигналы и непрерывный ответ оператора

- Сквозной поиск кодов/текста и пагинация Signals/HITL, все статусы и область всех запусков в операторских списках.
- SIG→INC/HD/ESC/SR в карточке, сохранение выбранного запроса и черновика после продолжения.
- CI больше не маскирует ошибку lint/test/build последующей успешной командой; регрессия ожидает начальную detail-загрузку перед переходом.
- 0009 hitl_feedback: поздняя информация с идемпотентностью/историей без повторения графа или денег; wait_human и эскалация различаются.


## 30.10.2026 — T-266: продукты финансового эффекта

- /finance: выбор продуктов, Все, снятие выделения и режим исключения; один серверный фильтр для всех моделей, графика и реестра.
- API all/include/exclude валидирует справочник; глобальная дедупликация выполняется до фильтра, unknown сохраняется. Новых миграций после 0008 нет.


## 29.10.2026 — T-265: демо-калибровка и рабочий контур (E24)

- Два независимых блока рядом на /finance: синтетическая демо-калибровка и рабочий допуск данных; provenance и метрики validation. Старые/неподдержанные источники остаются unknown.
- Одна риск-оценка на клиента за запуск, возвраты по всем кейсам, один штраф на последнюю версию сделки. go без временного доказательства суммы не даёт.
- Append-only financial_evidence (0008), GET assessment и POST evidence, форма/история в модале, checksum и идемпотентность. Промпты, LLM-схемы, проводки, HITL и основная формула не менялись.
- ADR-0014 и источник данных data/economics, генератор/CLI калибровки, regression tests. Календарные фильтры приведены к UTC независимо от часового пояса соединения БД.

## 29.10.2026 — финансовый эффект запуска (E24, cross-layer, contract-change)

- /finance: три независимых варианта на одном экране, возвраты/net, периоды и запуски, накопленный ряд, пагинация и детализация. Вероятность оттока и штраф явно сценарные; формула ADR-0007 сохранена.
- Additive REST total/detail и generated TS types; WS metrics/FINANCIAL_IMPACT_UPDATED, восстановление через polling. Отсутствующие/устаревшие расчёты помечены.
- Исправлен пересчёт при смене статуса без подарка; сохранены политики HITL и денежные проводки. Сопоставление входа и ADR-0013; E24/T-264/T-265 (#87–#89).

## v1.11.0 — 27.10.2026 — ТЗ v1.5: кабинет менеджера продукта, CSI и ВСП, дизайн-система v2, «Путь обращения», «Поиск и след» (только документация)
- Вход: четыре файла из `Downloads/дополнительные тз 2026-10-27/` (ЕТЗ «кабинет менеджера продуктовой команды», прототип 2.4, два эталонных интерфейса); конспект — `docs/TZ-additional-2.md`.
- `docs/TZ.md` → v1.5: матрица 0.7, пункты 1.2/1.3, роли-пресеты, 12.2 (п. 12–17), 13, 14.1 (CX Index), 16.4, эпики E19–E23 в §17, сценарии 12–15, блоки демо E–F, критерии 34–46, открытые вопросы 11–22, журнал решений 20.7 (№ 33–66), новые разделы 24–28; «Источники» теперь раздел 29.
- `docs/TZ-merge-v1.5-analysis.md`: реестр конфликтов № 33–66 с решениями, дрейф документации, риски, план contract-change, 12 открытых вопросов.
- Карточки T-223…T-263 (41 шт., волны 7–9, слои L1–L5) в `scripts/gen_tasks_v15.py`, подключены к `scripts/gen_tasks.py`; индекс `docs/tasks/README.md` пересобран (191 карточка), статусы и отчёты сохранены.
- `AGENTS.md` (§3, §6.11, §9), `docs/TEAM-SPLIT.md`, `docs/DEMO-SCRIPT.md`, `README.md` — ссылки и описание нового плана.
- **Решения техлида 27.10.2026** (ТЗ 20.7 № 67–73): рабочий день симулятора 09:00–18:00 (ТЗ 4.1 приведено к коду); циркадный режим на защите — по симуляционному времени; пакет тем `ops` — запасной, в шапке селектор темы; отчёт по направлению — печатная форма «отчёт для человека» с выводами на русском без LLM (24.5, T-244); названия площадок отзывов показываются текстом (`data/platforms.yaml`); расширение `pg_trgm` разрешено; порядок E22/E23 → E19/E20.
- **Новые железные правила AGENTS.md 19–20**: «След» и «Путь» — только чтение без LLM и записи; роли — пресеты, а не доступ, красные слова/направления/ставки — данные.
- **Сверка дрейфа (T-261, закрыта)**: AGENTS.md §2/§3/§6.5/§6.9/§9 и правило 10 приведены к фактической структуре фронта (`pages/`, `widgets/`, `shared/`, токены в `index.css`); React Flow помечен как разрешённый, но не подключённый; создан `docs/adr/` (README, шаблон, ADR-0001…0011 — T-153 закрыта); статусы карточек: T-195, T-198 → `done`, T-007, T-015, T-119 → `in_progress` с остатком; новая карточка T-263 (локальные шрифты OFL).
- **Не изменялись** (требуют `contract-change` и решения техлида, карточки T-223/T-237): `contracts/`, `CODEOWNERS`, код backend/frontend, `data/`.

## v1.10.0 — 22.10.2026 — задачи и подарки, мастер правит .env, живое распознавание речи с микрофона (B10) (cross-layer, contract-change)
- **Задачи** (T-079/T-080): `GET /api/tasks` (фильтры kind / status[] / requires_hitl / ready / run_id, `counts` по kind:status, в элементе — клиент, инцидент, название подарка, `ready`, `overdue`), `POST /api/tasks/{id}` approve / change / reject / done. Подарок при approve / change выдаётся: уведомление клиенту по шаблону `gift_offer`, флаг `gift_issued` у инцидента, статус `done`; change проверяет каталог и сегмент (422). Вкладка «Задачи» на рабочем месте: фильтры, «Выдать все готовые», замена подарка.
- **Мастер правит `.env`** (T-009): `GET/PUT /api/settings/env` (`app/api/envfile.py`) — белый список ключей, секреты маскируются («…1234»), запись в файл на месте с сохранением комментариев и порядка, горячее применение: переменные процесса → кэш Settings → пересборка цепочки LLM и подмена в агенте без перезапуска (PROFILE / SIM_SEED помечаются как требующие перезапуска). В Docker `.env` смонтирован в `/data/env/.env` (`ENV_FILE`). Шаги мастера LLM / Эмуляция / Каналы получили редакторы соответствующих переменных; `test-tgbot` берёт токен из `.env`, если поле пустое.
- **STT и живая встреча** (B10: T-181 / T-182 / T-183 / T-193 / T-206): пакет `app/stt/` — `base.py` (интерфейс, split стерео), `vosk_provider.py` (офлайн Vosk, ленивая загрузка модели, по рекогнайзеру на канал), `browser.py` (Web Speech API, реплики текстом), `registry.py`, `speakers.py` (авто-атрибуция спикера по маркерам речи), `live.py` (сессия: реплики → детектор → алерты → отчёт `_finish_report` при закрытии, `stt_metrics`), `audio_ws.py` (`/ws/audio/{session_id}`: hello → ready, PCM16 16 кГц 1–2 канала или `{type: text|speaker|end}`, тишина 90 с). `POST /api/compliance/sessions` с `source=mic` создаёт сессию и отдаёт `audio_ws_url`; `GET /api/stt/providers`, `POST /api/stt/test` (WER по `data/stt/sample_ru_16k.wav`), **новый** `POST /api/stt/transcribe` (надиктовать: PCM/WAV → текст). Frontend: кнопка «Микрофон» на «Комплаенс» → панель «Живая встреча» (ВСП, сотрудник, продукт, провайдер, режим спикеров manual / auto / stereo, уровень сигнала, пробел — переключить спикера, стенограмма с partial, срабатывания, отчёт), «Надиктовать» в режиме жюри (`VoiceInput`: офлайн через сервер или Web Speech API), проверка STT в мастере (шаг «Каналы»). Модель: `make stt-model` (vosk-model-small-ru-0.22, в git не хранится; `.gitignore`, `.dockerignore`).
- **contract-change** (OpenAPI): `GET /api/tasks` — параметры `status[]`, `requires_hitl`, `ready`, `run_id`; `Task` + `resolved_sim`, `run_id`, `incident_*`, `gift_name`, `ready`, `overdue`; `TaskList.counts`; новые `GET/PUT /api/settings/env` и схемы `EnvVar` / `EnvUpdate` / `EnvResult`; `test-tgbot.token` необязателен; новый `POST /api/stt/transcribe`. БД не менялась.
- Тесты: `tests/integration/test_tasks.py`, `test_env_editor.py`, `test_stt_live.py` (browser-провайдер всегда; Vosk — при наличии модели), `tests/unit/test_stt.py`.

## v1.9.0 — 22.10.2026 — мастер настройки и настройки стенда (cross-layer, contract-change)
- API `setup` (T-009): `GET /api/setup/status`, `PUT /api/setup` (разделы llm / bank / sim / channels / policies / economics / ui — частично, шаги отмечаются выполненными; `sim` пишет seed и интенсивности в `sim_state`, `policies` — в `settings.policies`, которые агент читает при каждом запуске), `POST /api/setup` (завершить), `POST /api/setup/test-llm` (реальный вызов провайдера: mock / gigachat / openai_compatible, для OpenRouter — остаток лимита из `GET /api/v1/key`), `POST /api/setup/test-tgbot` (getMe), `POST/GET /api/setup/generate` (фоновый запуск `scripts/seed/run.py` с логом, прогрессом и матрицей покрытия).
- API `settings` (T-009): `GET/PATCH /api/settings`, `export`/`import` одним JSON (без секретов), `sla-matrix` (ровно 9 ячеек, report_days ≤ fix_days), `routing-rules` (проверка команд), `llm-profiles` CRUD (удаление запрещено при ссылках из agent_runs), `llm-keys` (шифруются `APP_SECRET`, `app/llm/secrets.py`; наружу — только хвост), `templates`, `gifts`, `economics` (+ ставки; инциденты пересчитываются лениво), `psychotypes` (сумма долей по сегменту = 1). Заглушек 501 с T-009 не осталось.
- **contract-change** (OpenAPI): `EconomicsSettings` + `misselling_case_cost_rub`, `map_zone_thresholds` (столбцы уже были в `economics_settings`); `SetupPayload.policies.hitl_rules` — `additionalProperties: number` с перечнем ключей.
- Frontend (T-010): страница `/setup` «Мастер настройки» — 9 шагов (LLM → Банк и клиенты → Эмуляция → Каналы → Политики агента → SLA и маршрутизация → Экономика → Шаблоны и двойники → Данные и запуск), индикатор выполненных шагов, экспорт/импорт, пункт «Настройки» в шапке.
- Тесты: `tests/integration/test_setup_settings.py` (round-trip всех разделов, валидации 422/409, генерация lite до `done`, шифрование ключей).

## v1.8.0 — 22.10.2026 — тикеты, эскалации, действия оператора, нагрузка команд (cross-layer, contract-change)
- API: `GET /api/tickets` (фильтры статус/отдел/приоритет/эскалация/поиск, `total`), `GET /api/tickets/{id}` (инцидент, эскалации, история статусов, цепочка решений), `GET/POST /api/escalations`, `GET /api/escalations/{id}` (сигнал, тикет, решение HITL, цепочка), `POST /api/escalations/{id}/ack` (acknowledged | resolved | dismissed с резолюцией; при закрытии последней эскалации инцидент возвращается в `in_progress`), `POST /api/incidents/{id}/actions` (take, reroute, reply_client, request_client_data, close, reject, mark_duplicate, change_priority, escalate — все по FSM ТЗ 8.3, `actor_type = human`), `GET /api/teams/load`, `GET /api/incidents/{id}/artifacts`.
- **contract-change** (OpenAPI): в `POST /api/incidents/{id}/actions` добавлены `action = take` и поле `actor`. Decision-chain (`/api/agent/runs/{id}/decision-chain`) приведён к схеме `events/agent/decision_chain.schema.json` (`step`, `tool`, `args` с маскированием ПДн, `result_brief`, `why_ru`, `latency_ms`, `wraps`, `router_action`, `llm_source`).
- Frontend: вкладка «Тикеты» (таблица ДТЗ FR-3.2, фильтры, выезжающая карточка с действиями сотрудника, эскалациями, историей и цепочкой решений) с режимом «Эскалации» (очередь руководителю FR-3.4: принять / закрыть с резолюцией / отклонить); вкладка «Команды» (нагрузка, SLA под угрозой и сорванные, отчёты, время взятия, доля в SLA).
- Тесты: `tests/integration/test_tickets_escalations.py` (действия по FSM, эскалация → ack → resolve → возврат инцидента в работу, 409/422).

## v1.7.0 — 22.10.2026 — B08/B14 карта, зоны, KPI-дашборд и экономика dCLTV (cross-layer)
- `app/economics/dcltv.py`: формула ТЗ 14.4 (пострадавшие × доля детракторов × доля невозврата × (ставка + премиальная надбавка)), выбор ставки продукт → система → канал → fallback, класс исхода по статусу/SLA/подарку/регрессии/уходу, upsert `incident_economics` с `formula_ru`, ленивый пересчёт для открытых инцидентов, `calibration_mode = simulated` подставляет фактические коэффициенты удержания из `v_retention_by_outcome` (выборка ≥ 10).
- API: `/api/map/heat` (слои signals/critical/incidents/churn, окно, запуск), `/api/map/regions/{code}/cities`, `/api/map/zones` (индекс концентрации негатива + copilot, пороги `map_zone_thresholds` c `critical_red`), `/api/metrics/dashboard` (ТЗ 14.1), `/api/metrics/economics[/live|/fact|/fact/export|/calibrate]`, `/api/notifications`, `/api/incidents/{id}/economics`; в карточке инцидента `economics` заполнено.
- Frontend: вкладки «Карта» (TopoJSON 83 субъектов, `src/shared/geo/`, маркеры для субъектов без полигона, режимы Тепло/Зоны, drill-down до городов), «Дашборд» (12 KPI, экономика с группировкой, факт по симуляции, калибровка, CSV), «Уведомления» (центр исходящих); верхняя полоса KPI переведена на один запрос `/api/metrics/dashboard`.
- Тесты: `tests/unit/test_economics.py` (пример ТЗ 631,52 ₽), `tests/integration/test_map_metrics.py`.

## v1.6.0 — 22.10.2026 — B06/B16 Mock-АБС и публичная лента (cross-layer)
- Backend `app/abs/`: счёт на клиента, проводки двойной записи (`ledger_entries`: debit/credit/fee/refund), идемпотентный возврат по `correlation_id`, инвариант `balance = Σ проводок`, догоняющие проводки для операций сида/сценариев (`backfill_ledger` при старте, `post_operation` в генераторе). Политика автономии (ТЗ 9.3) теперь читает факты из АБС: «уже был возврат по операции», «возвратов за 30 дней».
- Агент: узел `act` возвращает комиссию инструментом `refund_fee` (автономно в лимите или после решения человека), закрывает инцидент как `resolved`, сканирует затронутых (`find_affected_clients`) и при массовом ударе ставит задачу `mass_refund` (HITL); текст клиенту — факт «возвращено», не обещание.
- `app/feed/`: посты эмулятора площадки (`external_posts`/`external_replies`), ответ под постом без ПДн и обещаний (`sanitize_public_text`), статусы `replied|escalated_to_dm`, статистика `v_feed_latency`. Посты создаются для всех публичных сигналов: симулятор, сценарии, жюри, `POST /api/public/reviews` (сопоставление автора по `card_last4`).
- API: `/api/abs/accounts/{client_id}`, `/api/abs/ledger`, `POST /api/abs/refunds` (HITL/массовый), `/api/public/feed[/{id}]`, `POST /api/public/reviews`, `POST /api/feed/{id}/reply`, `/api/feed/stats`, `/api/rules` (GET/PUT с версионированием, `POST evaluate`, `GET evaluations`).
- Frontend `/feed`: лента с фильтром по площадке, форма публикации отзыва, ветка ответов с латентностью, виджет «АБС (эмуляция)» с подсветкой возврата; WS-топики `feed`, `abs`.
- Сценарий 8 проверяет `refund`, `public_reply`, `abs_widget` (ранее NOT_YET). Тесты: `tests/integration/test_abs_feed.py`, `tests/unit/test_feed_sanitize.py`.

## v1.5.1 — 22.10.2026 — логирование и отчёт о качестве (T-222)
- JSONL-журнал structlog `backend/var/log/app.jsonl`, HTTP-метрики процесса, отчёт «что сломалось / работает не так / доработать» с рекомендациями и индексом здоровья: `GET /api/reports/quality|http|log`, `make report` → `data/reports/`, вкладка «Качество» на `/engine`. Контракт: `QualityReport`, `HttpStats`. Руководство — `docs/REPORTS.md`.

## v1.5.0 — 22.10.2026 — B07 комплаенс-контроль по транскриптам (cross-layer, contract-change)
- Backend `app/compliance/`: TXT/JSON-парсер транскриптов, таксономия и rule-детектор (8 паттернов, нечёткие фразы, факт-чек по `products.tariffs`, скрипт обслуживания с отрицаниями), LLM-детектор (`misselling_detect`, `transcript_report`; mock = правила; откат на правила при сбое), сессии/триггеры/счётчик/алерты/инциденты, отчёт (json|md) и отправка руководителю. API `/api/ingest/transcripts*`, `/api/compliance/*` реализованы (501 только для mic/file — B10).
- Сценарии 9 и 10 работают по файлам корпуса; корпус `data/import/transcripts` (20) проверяется тестом `tests/compliance/test_corpus.py` против `data/bench/transcripts_v1`.
- Frontend: `/compliance` (транскрипты, отчёт, реплики, статистика) и `/manager` (алерты с решением в один клик).
- Контракт: enum кодов паттернов в OpenAPI расширен до 8 (`MissellingPattern.code`, `ComplianceTrigger.pattern_code`); `.env.example` — `COMPLIANCE_ALERT_THRESHOLD`.

## v1.4.3 — 22.10.2026 — рабочий цикл одной командой
- `scripts/cx.py`: `doctor / next / start / check / pr / fix / status / done / clean / open` — worktree `../wt/<id>`, ветки `feat/T-NNN` и `pkg/Bxx`, окружение, промпт из `scripts/prompts/task.md`, запуск `codex exec` без участия человека (или Cursor/manual), проверки, PR через `gh` с отчётом агента и автоматическими метками `contract-change`/`cross-layer`, уборка после слияния. Состояние — `.cx/state.json`.
- `docs/WORKFLOW.md` (что такое worktree, пять команд, день целиком, что делать при сбоях); TEAM-SPLIT §4 и PLAN-14D §3 переведены на `cx`; AGENTS.md §3–4, §5.1.
- `.gitignore` в пакете (`.env`, `.cx/`, окружения, большая модель Vosk) — T-001 дополняет, не создаёт с нуля.

## v1.4.2 — 21.10.2026 — репозиторий GitHub, CI и проверка DDL на реальной базе
- Рабочий репозиторий — `github.com/florren/vibebashers`, зеркало в GitVerse (`mirror.yml`, уже в репозитории, проверено). `docs/REPO-BOOTSTRAP.md`: порядок заливки пакета при защищённой `main`, ruleset, тестовый PR.
- `.github/workflows/ci.yml`: job'ы `contracts`, `db` (PostgreSQL 16 service: `schema.sql`, идемпотентные 0002/0003 дважды, инварианты), `owners` (границы слоя в PR), `tests` (uv, ruff, mypy, pytest, npm — включаются по мере появления кода). Имена job'ов зафиксированы для ruleset.
- DDL проверен на реальном PostgreSQL (18): чистая v1.4, идемпотентность миграций, пути v1.2 → 0002 → 0003 и v1.3 → 0003, откат 0003 и повторный накат — 74 таблицы. Исправлено: `v_tickets` ссылалось на `clients.segment` вместо `clients.segment_code` (schema.sql и 0003).
- `Makefile`: алиас `check-contracts`; стек: `uv` как менеджер Python-окружения; AGENTS.md §2–3, §5.1; T-001 (CI усиливается без переименования job'ов, uv); TEAM-SPLIT §3/§6; PLAN-14D; ТЗ 16.3; CODEOWNERS (логины GitHub).

## v1.4.1 — 21.10.2026 — слои, владение и режим без ревьюера
- `docs/PLAN-14D.md`: спринт 22.10–4.11 — вертикальный демо-срез, 26 пакетов карточек по трём рабочим местам (Codex / Cursor / Perplexity Computer) и интегратору, список урезаний, контрольные точки с правилом отсечения, рычаги ускорения.
- `docs/TEAM-SPLIT.md`: пять слоёв L1–L5 с каталогами и субагентами, раскладка на 1–3 участников, режим слияния без ревьюера, распорядок для участника без опыта разработки, оценка сроков с учётом лимитов инструментов.
- `CODEOWNERS`, `scripts/check_owners.py` (`make check-owners`), `.github/pull_request_template.md`.
- Карточки: поля «Слой» и «В демо-минимуме»; индекс `docs/tasks/README.md` — колонки «Слой» и «Демо-мин.», раздел «По слоям» со сводкой объёмов.
- `AGENTS.md` §5.1, структура, §9; `CLAUDE.md`, `.cursor/rules`.

## v1.4 — 21.10.2026 — слияние с дополнительным ТЗ (FR-1 … FR-5)

Вход: `docs/TZ-additional.md` (приём транскриптов и сообщений, NLP-модуль, агент-маршрутизатор на tool calling, анализ транскрипта сотрудника, карта с зонами). Матрица покрытия — ТЗ 0.6, 15 конфликтов и решения — ТЗ 20.6 и `docs/BRD-merge-analysis.md` (раздел «Дополнительное ТЗ»).

### Документы
- `docs/TZ.md` → v1.4: 0.6 (матрица FR → ТЗ), 1.2 п. 19–22, 1.4 (принцип «имена наружу — из ТЗ заказчика»), 3.6–3.7 (приёмный слой, транскрипты, адаптеры), 7 (`sentiment`, `hidden_negativity`, `problem_summary`), 9.2 (роутер-инструменты), 9.3 (политика эскалации и уточнения), 9.7 (тикетница, эскалации, цепочка решений), 12.2 (зоны карты, тикер, поля ленты, вкладка «Транскрипты»), 12.5, 13, 14.1, 14.3 (наборы `sentiment_v1`, `hidden_negativity_v1`, `summary_v1`, `red_phrases_v1`, `transcripts_v1`), 16.4, 17 (E18), 18 (сценарии 10–11, блок D), 19 п. 26–33, 20.3 п. 7–10, 20.6, 22.8–22.9, 23.
- `AGENTS.md`: §1, стек, структура (`app/ingest`, `app/tickets`, данные ДТЗ), команды, железные правила 17–18, 6.2/6.8 дополнения, новая 6.10, §9 (E18, 150 карточек, критический путь v1.4), §10–11.
- `docs/tasks/`: 15 новых карточек T-207…T-221 (эпик E18), волны 2–4, демо-минимум v1.4.

### Контракты
- `contracts/db/schema.sql` v1.4 (74 таблицы, 9 представлений): `ingest_sources`, `ingest_messages`, `transcripts`, `escalations`, `service_scripts`; `signals.geo/sentiment/transcript_id`, `incidents.routing_status/problem_summary`, `misselling_patterns.family/alert_policy/immediate_threshold/recommendation_ru/training_module`, `compliance_triggers.recommendation_ru/fact_check`, `compliance_alerts.kind/recommendation_ru/transcript_id`, `audio_sessions.pacing/transcript_id/report`, `economics_settings.map_zone_thresholds`; CHECK `signals.origin += transcript, polling`, `compliance_alerts.decision += acknowledged`; представления `v_tickets`, `v_map_zones`; каналы NOTIFY `ingest`, `escalations`, `tickets`, `zones`.
- `contracts/db/migrations/0003_additional_tz.sql` + `alembic/versions/0003_additional_tz.py` (идемпотентно; downgrade возвращает v1.3).
- `contracts/api/openapi.yaml` 1.4.0: 131 путей (+21), 111 схем; теги `ingest`, `tickets`, `escalations`; `/api/ingest/messages`, `/api/ingest/transcripts*`, `/api/ingest/sources*`, `/api/public/mock-social-feed`, `/api/tickets*`, `/api/escalations*`, `/api/agent/runs/{id}/decision-chain`, `/api/compliance/transcripts/{id}/report|send`, `/api/compliance/scripts`, `/api/map/zones`, `/api/metrics/economics/live`, `/api/bench/sentiment`; поля `sentiment`, `geo`, `problem_summary`, `routing_status`, `channel` в `Signal`/`IncidentBrief`.
- `contracts/events/` (36 схем): новые `ingest/unified_message`, `ingest/transcript`, `ingest/ingest_event`, `agent/router_tools`, `agent/decision_chain`, `sim/escalation`, `sim/zone`, `compliance/transcript_report`; расширены `common` (+14 перечислений, флаги `passive_aggression`, `repeat_contact_7d`), `agent/normalization` (`sentiment`, `hidden_negativity`), `agent/classification` (`sentiment`, `problem_summary`), `agent/decision` (`router_action`, `escalation`, `clarification_question_ru`), `agent/tool_call` (+4 инструмента, `wraps`), `compliance/misselling_verdict` и `session_event` (семейство, рекомендация, `pacing`, `compliance.report_ready`), `envelope` (семейства `ingest|escalation|zone`), `ws/message` (топики `ingest`, `escalations`, `tickets`, `zones`, `metrics`).
- `Makefile`: `import-transcripts`, генерация схем `ingest` в `sync-contracts`.

Проверка: `python scripts/contracts_check.py` → 36 схем, 131 путей; `python scripts/gen_tasks.py` → 150 карточек.

## v1.3 — 21.10.2026 — слияние с бизнес-требованиями демо-стенда (BRD)

Вход: `docs/BRD.md` (сценарий 1 — внешние площадки и автономный возврат; сценарий 2 — аудиомониторинг и мисселлинг; NFR Log/Debug и отказоустойчивость демо). Обоснование решений и 17 конфликтов — `docs/BRD-merge-analysis.md`, журнал решений — ТЗ 20.5.

### Документы
- `docs/TZ.md` → v1.3: разделы 0.5 (матрица BRD → ТЗ), 1.2 п. 14–18, 1.3–1.4, 3.4 (stateful Mock-АБС), 3.6 (каналы `review_portal`, `voice_input`, `branch_audio`), 4.7 (живые контуры), 5.3 (`STTProvider`), 5.4 (подстраховка), 6 шаг 7a (быстрый путь), 8.1 (`instant`, `fee_refund`, `misselling`), 9.6 (Rules Engine), 11 и 12.2 экран 7 («Надиктовать»), 12.2 экраны 8–10, 12.6 (панель Log), 12.7 (меню демонстратора), 13 (17 таблиц), 14.3 (наборы `reviews_v1`, `misselling_v1`, `stt_v1`), 16.4 (бюджеты задержек), 17 (E15–E17), 18 (сценарии 8–9, демо-скрипт), 19 п. 18–25, 20.3, 20.5, 21–22 (новые разделы), 23 (источники).
- `AGENTS.md`: §1–4 (контуры, STT в стеке, структура, команды, HTTPS), железные правила 14–16, подсистемы 6.7–6.9, дополнения 6.2–6.6, §7 (идемпотентные миграции), §9 (E15–E17, сквозные), §10–11.
- `docs/tasks/`: 36 новых карточек T-171…T-206 (135 всего), волны и демо-минимум v1.3, критические пути контуров.

### Контракты
- `contracts/db/schema.sql` v1.3: 17 новых таблиц, колонки `clients.social_handles/refunds_30d`, `client_products.card_last4`, `operations.method/merchant/fee_amount`, `signals.voice_meta/external_post_id`, `economics_settings.misselling_case_cost_rub`, `incident_economics.refund_amount_rub`; CHECK-перечисления `sim_runs.kind += live`, `incidents.incident_type += fee_refund, misselling`, `incidents.complexity += instant`, `incidents.created_by += compliance`, `signals.origin += review_portal, voice_input, api`, `agent_runs.kind += compliance_detector, speaker_attribution`; представления `v_feed_latency`, `v_compliance_by_employee`; каналы NOTIFY `feed`, `abs`, `compliance`, `stt`, `demo`.
- `contracts/db/migrations/0002_brd_contours.sql` + `alembic/versions/0002_brd_contours.py` (идемпотентно; downgrade возвращает v1.2).
- `contracts/api/openapi.yaml` 1.3.0: +31 путь (теги `feed`, `abs`, `rules`, `compliance`, `stt`, `demo`), `/ws/audio/{session_id}`, `voice_meta` в `POST /api/signals` и `POST /api/public/claim`, +28 схем.
- `contracts/events/`: `common` (+17 перечислений, расширены `team`, `channel`, `flag`, `complexity`), `envelope` (семейства `review|abs|compliance|demo`), `ws/message` (топики `feed`, `abs`, `compliance`, `stt`, `demo`), `agent/tool_call` (+6 инструментов, `source`), `agent/decision` (`fast_path`, `rule_codes`), `agent/classification` (`negativity`, `intents`); новые `agent/normalization`, `agent/client_match`, `agent/rule_violation`, `agent/instant_decision`, `rules/rule_condition`, `sim/review`, `sim/abs`, `compliance/session_event`, `compliance/misselling_verdict`, `compliance/speaker_attribution`, `compliance/stt_result`, `demo/failover`.
- `Makefile`: цели `tasks`, `cassettes-record`, `stt-bench`, `demo-offline`; `sync-contracts` копирует `migrations/` и генерирует схемы `compliance`/`rules`.

Проверка: `python scripts/contracts_check.py` → 28 схем, 110 путей; `python scripts/gen_tasks.py` → 135 карточек.

## v1.2 — 21.10.2026
Запуски эмуляции (`sim_runs`, `run_id`), прерывание/возобновление, baseline-снимки (ТЗ 4.6).

## v1.1 — 20.10.2026
Модель поведения клиентов, калькулятор «Факт», ADR, карточки задач.

## 30.10.2026 — T-268/T-269: дальнейший план по сведениям и отдельный чат

- 0010: надёжная обработка поздней информации отдельным агентским review, атомарные новые задачи/приоритет и свежий контекст; без replay старого act/денег/решения.
- Отдельная сборка UI и публичный FastAPI :9999, анонимные формы/диалог/Vosk, cookie-изоляция, пассивные защиты, ui_pers_demo в Signals.
- install.sh готовит модель и поднимает управляемый Tuna; ключи только .env → окружение CLI, инспектор выключен, readiness проверяется по HTTPS.

### 30.10.2026 — T-270/T-271: безопасная установка и обращение к посетителю

- Seed --if-needed сохраняет существующий стенд, честно сообщает coverage/baseline и останавливает install при первичных ошибках; Docker содержит PostgreSQL client 16 из подписанного PGDG.
- В чате :9999 необязательное имя/псевдоним, история подписей и восстановление своей сессии; имя передаётся агенту без банковской идентификации. OpenAPI 1.5.7, схема БД не менялась.


### 30.10.2026 — T-272/T-273/T-274

- Добавочный CSI-ремонт старого baseline до полного покрытия без reset и изменения прежних решений.
- Устранена автономная mock-генерация по реальному таймеру; legacy fake не возобновляет агента после рестарта.
- Первый явный HTTP-вход при пустом current_run_id создаёт live без старта часов (согласовано отдельно).
- Доказательства до/после, fixed-seed и регрессии сохранности: ADR-0019 и docs/benchmarks/idle-generation.

### 30.10.2026 — T-275: CSI после восстановления baseline

- Restore совместимого архива автоматически выполняет атомарный CSI-ремонт до finished/start; полный архив — no-op, повторный restore не накапливает дубли.
- Dump, restore и ремонт используют БД переданного соединения с сохранением аутентификации вместо глобального DATABASE_URL.
- Ошибка ремонта не объявляется успешным restore и не стартует новый сценарий. Формат старого pg_dump 18 и миграции его схемы — отдельная согласованная задача #108.

## 30.10.2026 — поиск связанных сущностей, экономика и baseline #108

- Фильтры SIG/INC/связанных кодов на finance/engine/compliance/manager; выбор сигнала в journey.
- Расчёт во вкладке экономики инцидента, калькулятор `/economics` с общей формулой backend.
- Изолированная подготовка старого dump, контроль provenance/SHA256, атомарный restore
  без игнорирования SQL-ошибок и с корректным сохранением зависимостей sim_runs.

## 31.10.2026 — нормализация GigaChat и учёт HITL/follow-up

Отдельный общий бюджет нормализации 10 секунд с резервом живой основной модели;
20/20 live-кейсов кандидата против 19/20 для прежней политики на 8 и 10 секундах.
Восстановление токенов, latency, стоимости, seq и текстового бюджета при продолжении
HITL/follow-up. Регрессии и воспроизводимый live-бенчмарк — ADR-0021.

## 31.10.2026 — demo-исполнение команд и сотрудников

- `/journey`: запуск и остановка изолированного demo-run, выбор пяти исходов команды, эмуляция сотрудников с сохранением ручного ввода.
- LLM-отчёты команды и ответы клиентам по фактам проверки, явные demo/source/model, персистентные планы и защита от повторных действий.
- 20 тематических синтетических входов; анализ покрытия и ограничений — `docs/DEMO-EXECUTION.md`.
- OpenAPI 1.5.9, аддитивный `/api/demo/execution`; без миграции БД и расширения денежных полномочий.


## 31.10.2026 — #124: общий цикл команд, сотрудников и ручных входов

- Общие Start/Pause/Stop синхронизированы с demo execution; отмена банковского тика атомарна.
- Жюри и Journey подключены к командам, сотрудникам и конечным ответам; настройки общего профиля сохраняются.
- Устранены блокировка готовых планов посторонними входами и наследование фактов чужого сценария.
- OpenAPI 1.5.10, аддитивный `mode=simulation`; воспроизводимая live-матрица `--matrix` 20 × 5.

## 31.10.2026 — #131, публичный чат и история

- ui_pers_demo включён в общую ускоренную цепочку команд/сотрудников при паузе.
- Создание paused live-run публичным процессом согласовано с операторским worker.
- Reject не создаёт orphan followup; добавлен read-only аудит и явное восстановление
  выбранного ожидания после отказа без повторных уведомлений, денег или подарков.
