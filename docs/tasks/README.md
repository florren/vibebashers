# Карточки задач субагентам (ТЗ v1.4)

Одна карточка — одна ветка — один PR (AGENTS.md §5 п. 12). Перед стартом субагент читает AGENTS.md, разделы ТЗ из карточки и указанные контракты. Нумерация по эпикам; номера внутри эпика не обязаны идти подряд. Волна — порядок запуска: задачи одной волны ведутся параллельно разными субагентами с соблюдением указанных зависимостей внутри волны; следующая волна начинается, когда закрыты зависимости её карточек.

## Волны

### Волна 1 — Фундамент (каркас, контракты в коде, справочники, LLM-интерфейс)

| Карточка | Эпик | Слой | Субагент | Оценка | Демо-мин. | Зависит от |
|---|---|---|---|---|---|---|
| [T-001](T-001-skelet-repozitoriya-makefile-env-example-pre-com.md) Скелет репозитория, Makefile, .env.example, pre-commit, CI | E1 | L1 | `SA-Infra` | M | да | — |
| [T-002](T-002-docker-compose-i-dockerfile-y-postgres-backend-f.md) Docker Compose и Dockerfile'ы (postgres, backend, frontend, mailpit, tgbot) | E1 | L1 | `SA-Infra` | M | да | T-001 |
| [T-004](T-004-karkas-fastapi-konfig-logirovanie-oshibki-health.md) Каркас FastAPI: конфиг, логирование, ошибки, health, settings | E1 | L1 | `SA-Infra` | M | да | T-001 |
| [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md) Применение schema.sql, SQLAlchemy-модели, сессии | E1 | L1 | `SA-DB` | L | да | T-001 |
| [T-006](T-006-sync-contracts-generaciya-enums-pydantic-shem-ts.md) sync-contracts: генерация enums, Pydantic-схем, TS-типов, проверка дрейфа OpenAPI | E1 | L1 | `SA-DB` | M | да | T-001 |
| [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md) Каркас frontend: Vite, TS strict, Tailwind-токены, темы, шрифты, роутинг, i18n-скелет | E1 | L4 | `SA-UI-Workspace` | M | да | T-001 |
| [T-011](T-011-spravochnik-subektov-i-gorodov-rf-svg-karta.md) Справочник субъектов и городов РФ + SVG-карта | E2 | L1 | `SA-Refs` | M | да | — |
| [T-012](T-012-segmenty-psihotipy-doli-psihotipov-po-segmentam.md) Сегменты, психотипы, доли психотипов по сегментам | E2 | L1 | `SA-Refs` | S | да | — |
| [T-013](T-013-produkty-sistemy-komandy-kanaly.md) Продукты, системы, команды, каналы | E2 | L1 | `SA-Refs` | S | да | — |
| [T-014](T-014-kody-oshibok-tipy-signalov-pravila-marshrutizaci.md) Коды ошибок, типы сигналов, правила маршрутизации, матрица SLA | E2 | L1 | `SA-Refs` | M | да | T-013 |
| [T-015](T-015-shablony-uvedomlenij-spravochnik-podarkov-stavki.md) Шаблоны уведомлений, справочник подарков, ставки dCLTV, параметры экономики | E2 | L1 | `SA-Refs` | M | да | T-012, T-013 |
| [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md) Интерфейс LLM-провайдера и структурированный вывод | E4 | L1 | `SA-LLM` | M | да | T-004, T-006 |
| [T-047](T-047-gigachat-provajder-s-pulom-klyuchej-i-uchetom-to.md) GigaChat-провайдер с пулом ключей и учётом токенов | E4 | L1 | `SA-LLM` | M | да | T-046 |
| [T-048](T-048-openai-sovmestimyj-provajder-openrouter-i-lokaln.md) OpenAI-совместимый провайдер: OpenRouter и локальная модель | E4 | L1 | `SA-LLM` | M | да | T-046 |
| [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md) Mock-провайдер (правила + шаблоны, детерминизм) | E4 | L1 | `SA-LLM` | M | да | T-046, T-014 |
| [T-141](T-141-testovaya-infrastruktura-backend.md) Тестовая инфраструктура backend | E11 | L5 | `SA-QA` | M | да | T-005, T-049 |

### Волна 2 — Данные, симулятор, каркас агента, модель поведения; v1.3 — Mock-АБС, правила, STT-воркер, replay, миграция 0002; v1.4 — миграция 0003, нормализатор ingest, транскрипты, корпуса ДТЗ

| Карточка | Эпик | Слой | Субагент | Оценка | Демо-мин. | Зависит от |
|---|---|---|---|---|---|---|
| [T-003](T-003-install-sh-ustanovka-odnoj-komandoj.md) install.sh: установка одной командой | E1 | L1 | `SA-Infra` | M | да | T-002, T-005, T-016 |
| [T-008](T-008-realtime-listen-notify-websocket-hab.md) Realtime: LISTEN/NOTIFY → WebSocket-хаб | E1 | L1 | `SA-Infra` | M | да | T-004, T-005 |
| [T-009](T-009-api-mastera-nastrojki-i-proverok-podklyucheniya.md) API мастера настройки и проверок подключения | E1 | L1 | `SA-Infra` | M | да | T-004, T-005, T-046, T-016 |
| [T-010](T-010-ui-mastera-nastrojki-9-shagov-i-ekran-nastrojki.md) UI мастера настройки (9 шагов) и экран «Настройки» | E1 | L4 | `SA-UI-Workspace` | L | да | T-007, T-009 |
| [T-016](T-016-generator-klientov-profili-lite-demo-stress.md) Генератор клиентов (профили lite/demo/stress) | E2 | L2 | `SA-Clients` | M | да | T-005, T-011, T-012 |
| [T-017](T-017-produkty-klientov-i-14-dnej-operacij.md) Продукты клиентов и 14 дней операций | E2 | L2 | `SA-Clients` | M | да | T-016, T-013 |
| [T-018](T-018-predystoriya-sboev-i-logi-sistem.md) Предыстория сбоев и логи систем | E2 | L2 | `SA-Logs` | M | да | T-017, T-014 |
| [T-019](T-019-biblioteka-tekstov-signalov.md) Библиотека текстов сигналов | E2 | L2 | `SA-Signals` | L | да | T-012, T-013, T-014 |
| [T-021](T-021-zolotoj-nabor-benchmarka-golden-v1-i-lite-v1.md) Золотой набор бенчмарка golden_v1 и lite_v1 | E2 | L1 | `SA-Refs` | M | да | T-019 |
| [T-031](T-031-simclock-sim-state-i-upravlenie-simulyaciej.md) SimClock, sim_state и управление симуляцией | E3 | L2 | `SA-Teams` | M | да | T-004, T-005, T-008 |
| [T-032](T-032-shina-sobytij-simulyatora.md) Шина событий симулятора | E3 | L2 | `SA-Teams` | S | да | T-031, T-006 |
| [T-033](T-033-generator-operacij-v-realnom-vremeni.md) Генератор операций в реальном времени | E3 | L2 | `SA-Teams` | M | да | T-032, T-017 |
| [T-034](T-034-generator-sboev-i-vosstanovlenij.md) Генератор сбоев и восстановлений | E3 | L2 | `SA-Logs` | M | да | T-032, T-018 |
| [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md) Сервис запусков эмуляции: sim_runs, run_id, режимы сброса, снимок baseline | E3 | L2 | `SA-Teams` | L | да | T-005, T-031, T-032 |
| [T-050](T-050-rate-limiter-byudzhety-fallback-i-maskirovanie-s.md) Rate limiter, бюджеты, fallback и маскирование секретов | E4 | L1 | `SA-LLM` | S | да | T-047, T-048, T-049 |
| [T-051](T-051-api-i-ui-profilej-llm-i-klyuchej.md) API и UI профилей LLM и ключей | E4 | L1 | `SA-LLM` | S | да | T-050, T-010 |
| [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md) AgentState, граф LangGraph, checkpointer, запуск по событиям | E5 | L3 | `SA-Agent` | L | да | T-046, T-032, T-005 |
| [T-057](T-057-instrumenty-chteniya-konteksta.md) Инструменты чтения контекста | E5 | L3 | `SA-Agent` | M | да | T-056, T-005 |
| [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md) Инструменты записи и побочных эффектов | E5 | L3 | `SA-Agent` | L | да | T-057, T-014, T-015 |
| [T-076](T-076-politiki-hitl-policies-py-i-testy.md) Политики HITL (policies.py) и тесты | E6 | L3 | `SA-Agent` | S | да | T-006, T-014 |
| [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md) Layout рабочего места CX: шапка, сим-часы, панель управления, KPI | E7 | L4 | `SA-UI-Workspace` | M | да | T-040, T-007, T-008, T-031 |
| [T-131](T-131-raschet-ekonomiki-dcltv-po-incidentu.md) Расчёт экономики dCLTV по инциденту | E10 | L2 | `SA-Economics` | M | да | T-005, T-015 |
| [T-153](T-153-nachalnyj-nabor-adr.md) Начальный набор ADR | E12 | L1 | `SA-Docs` | S | да | T-001 |
| [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md) Параметрическая модель состояний клиента | E14 | L2 | `SA-Behavior` | L | да | T-012, T-032, T-031 |
| [T-171](T-171-mock-abs-scheta-tarify-provodki-sid-i-invariant.md) Mock-АБС: счета, тарифы, проводки, сид и инвариант баланса | E15 | L2 | `SA-ABS` | L | да | T-005, T-017, T-040 |
| [T-172](T-172-rules-engine-business-rules-dsl-uslovij-uzel-che.md) Rules Engine: business_rules, DSL условий, узел check_rules и четыре правила v1 | E15 | L2 | `SA-ABS` | M | да | T-171, T-056 |
| [T-178](T-178-korpus-publichnyh-otzyvov-i-nabor-reviews-v1.md) Корпус публичных отзывов и набор reviews_v1 | E15 | L2 | `SA-Signals` | M | — | T-016, T-019, T-021 |
| [T-180](T-180-rasshirenie-zapuskov-avtosozdanie-run-kind-live.md) Расширение запусков: автосоздание run kind=live и независимость живых контуров от сим-часов | E15 | L2 | `SA-Teams` | S | да | T-040 |
| [T-181](T-181-sttprovider-i-vosk-vorker-s-modelyu-v-repozitori.md) STTProvider и Vosk-воркер с моделью в репозитории | E16 | L3 | `SA-STT` | L | да | T-004, T-005 |
| [T-184](T-184-taksonomiya-missellinga-i-rule-detektor-predvari.md) Таксономия мисселлинга и rule-детектор (предварительная отметка) | E16 | L3 | `SA-Compliance` | S | да | T-005, T-013 |
| [T-190](T-190-dialogi-otdeleniya-nabor-misselling-v1-predzapis.md) Диалоги отделения, набор misselling_v1, предзаписанные WAV с эталонами | E16 | L2 | `SA-Signals` | M | — | T-184, T-021 |
| [T-194](T-194-provajder-replay-kassety-zapisannyh-otvetov-mode.md) Провайдер replay: кассеты записанных ответов моделей, запись LLM_RECORD, воспроизведение потока | E17 | L1 | `SA-LLM` | M | да | T-046, T-047, T-049 |
| [T-199](T-199-migraciya-0002-primenenie-modeli-sqlalchemy-i-pe.md) Миграция 0002: применение, модели SQLAlchemy и перечисления v1.3 | E1 | L1 | `SA-DB` | M | да | T-005, T-006 |
| [T-200](T-200-openapi-1-3-i-json-shemy-v-kode-routery-zaglushk.md) OpenAPI 1.3 и JSON-схемы в коде: роутеры-заглушки, Pydantic, TS-типы, проверка дрейфа | E1 | L1 | `SA-DB` | M | да | T-006, T-004 |
| [T-205](T-205-agents-md-v1-3-pravila-14-15-podsistemy-6-7-6-9.md) AGENTS.md v1.3: правила 14–15, подсистемы 6.7–6.9, карта эпиков E15–E17, ADR по STT и правилам | E12 | L1 | `SA-Docs` | S | — | T-153 |
| [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md) Единая схема сообщения и нормализатор ingest: signals.geo/sentiment, каскад гео, journal ingest_messages | E18 | L3 | `SA-Agent` | M | да | T-221, T-056, T-058 |
| [T-208](T-208-priem-transkriptov-json-txt-parsery-post-api-ing.md) Приём транскриптов: JSON/TXT парсеры, POST /api/ingest/transcripts (JSON и multipart), импорт каталога, таблица transcripts | E18 | L3 | `SA-Agent` | M | да | T-207 |
| [T-219](T-219-korpusa-dtz-transcripts-v1-20-transkriptov-json.md) Корпуса ДТЗ: transcripts_v1 (20 транскриптов JSON/TXT с эталонами), red_phrases_v1 (120 реплик), сид service_scripts и mock-ленты | E18 | L2 | `SA-Signals` | M | да | T-190, T-178 |
| [T-221](T-221-migraciya-0003-i-openapi-1-4-v-kode-modeli-sqlal.md) Миграция 0003 и OpenAPI 1.4 в коде: модели SQLAlchemy, перечисления v1.4, роутеры-заглушки ingest/tickets/escalations, TS-типы | E18 | L1 | `SA-DB` | S | да | T-199, T-200 |

### Волна 3 — Узлы агента, команды и SLA, карта и ленты, бенчмарк; v1.3 — быстрый путь, матчинг, аудиосессии, детектор, панель Log; v1.4 — sentiment/скрытый негатив/problem_summary, роутер-инструменты и эскалации, красные фразы, пакетный анализ, адаптеры

| Карточка | Эпик | Слой | Субагент | Оценка | Демо-мин. | Зависит от |
|---|---|---|---|---|---|---|
| [T-020](T-020-predystoriya-signalov-incidentov-statusov-artefa.md) Предыстория сигналов, инцидентов, статусов, артефактов и состояний клиентов | E2 | L2 | `SA-Signals` | L | да | T-018, T-019, T-015, T-040, T-131, T-161 |
| [T-022](T-022-testy-dannyh-no-pii-pokrytie-idempotentnost-proi.md) Тесты данных: no-PII, покрытие, идемпотентность, производительность сида | E2 | L1 | `SA-DB` | S | да | T-016, T-017, T-018, T-019, T-020 |
| [T-035](T-035-generator-oshibok-klientov.md) Генератор ошибок клиентов | E3 | L2 | `SA-Teams` | S | да | T-032, T-033 |
| [T-036](T-036-emulyator-komand-i-cifrovoj-sled-incidenta.md) Эмулятор команд и цифровой след инцидента | E3 | L2 | `SA-Teams` | L | да | T-032, T-013, T-046, T-058 |
| [T-037](T-037-sla-dvizhok.md) SLA-движок | E3 | L2 | `SA-Teams` | M | да | T-031, T-032, T-014 |
| [T-041](T-041-preryvanie-i-vozobnovlenie-emulyacii-vosstanovle.md) Прерывание и возобновление эмуляции: восстановление после рестарта | E3 | L3 | `SA-Agent` | M | да | T-031, T-040, T-056, T-058 |
| [T-042](T-042-itogovye-metriki-zapuska-summary-i-eksport.md) Итоговые метрики запуска (summary) и экспорт | E3 | L2 | `SA-Economics` | S | да | T-040, T-132 |
| [T-059](T-059-uzly-ingest-normalize-identify-client-gather-con.md) Узлы ingest, normalize, identify_client, gather_context | E5 | L3 | `SA-Agent` | M | да | T-057 |
| [T-060](T-060-uzel-classify-i-prompty-v1.md) Узел classify и промпты v1 | E5 | L3 | `SA-Prompts` | L | да | T-059, T-046, T-021 |
| [T-061](T-061-uzel-decide-sla-marshrutizaciya-prioritet-politi.md) Узел decide: SLA, маршрутизация, приоритет, политики, проверка формулировок | E5 | L3 | `SA-Agent` | L | да | T-060, T-076 |
| [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md) Узел act: коммуникации клиенту и командам | E5 | L3 | `SA-Agent` | M | да | T-061, T-058 |
| [T-065](T-065-trassirovka-zapuskov-i-striming-tokenov.md) Трассировка запусков и стриминг токенов | E5 | L3 | `SA-Agent` | M | да | T-056, T-008 |
| [T-077](T-077-uzel-wait-human-ochered-hitl-i-vozvrat-resheniya.md) Узел wait_human, очередь HITL и возврат решения в граф | E6 | L3 | `SA-Agent` | M | да | T-056, T-061, T-008 |
| [T-087](T-087-lenta-signalov.md) Лента сигналов | E7 | L4 | `SA-UI-Workspace` | M | да | T-086, T-060 |
| [T-088](T-088-teplovaya-karta-rf-s-drill-down-do-gorodov.md) Тепловая карта РФ с drill-down до городов | E7 | L4 | `SA-Map` | L | да | T-086, T-011 |
| [T-089](T-089-doska-i-tablica-incidentov-s-indikatorami-sla.md) Доска и таблица инцидентов с индикаторами SLA | E7 | L4 | `SA-UI-Workspace` | M | да | T-086, T-058, T-037 |
| [T-091](T-091-klient-360.md) Клиент 360 | E7 | L4 | `SA-UI-Workspace` | M | да | T-086, T-161 |
| [T-129](T-129-benchmark-ranner-i-metriki.md) Бенчмарк-раннер и метрики | E10 | L3 | `SA-Bench` | L | да | T-060, T-050, T-021 |
| [T-132](T-132-api-svodnoj-ekonomiki-i-metrik-dashborda.md) API сводной экономики и метрик дашборда | E10 | L2 | `SA-Economics` | M | да | T-040, T-131, T-037, T-161 |
| [T-162](T-162-detekciya-snizheniya-aktivnosti-molchalivyj-uhod.md) Детекция снижения активности («молчаливый уход») и сигнал агенту | E14 | L2 | `SA-Behavior` | M | да | T-161, T-033, T-056 |
| [T-163](T-163-llm-dvojniki-podsvechennyh-klientov.md) LLM-двойники «подсвеченных» клиентов | E14 | L2 | `SA-Behavior` | L | да | T-161, T-046, T-049, T-065 |
| [T-164](T-164-uhod-klienta-churn-events-incident-account-closu.md) Уход клиента: churn_events, инцидент account_closure, закрытие продуктов | E14 | L2 | `SA-Behavior` | M | да | T-161, T-058, T-131 |
| [T-173](T-173-matching-klienta-po-kosvennym-dannym-match-clien.md) Матчинг клиента по косвенным данным (match_client_by_hints) | E15 | L3 | `SA-Agent` | M | да | T-171, T-057, T-059 |
| [T-174](T-174-bystryj-put-agenta-uslovnoe-rebro-act-instant-st.md) Быстрый путь агента: условное ребро, act_instant, structured output instant_decision | E15 | L3 | `SA-Agent` | L | да | T-172, T-173, T-060, T-061, T-062, T-076 |
| [T-175](T-175-instrumenty-refund-fee-find-affected-clients-get.md) Инструменты refund_fee, find_affected_clients, get_account_balance и массовый возврат через HITL | E15 | L3 | `SA-Agent` | M | да | T-171, T-172, T-058, T-077 |
| [T-176](T-176-priemnik-otzyvov-external-posts-replies-instrume.md) Приёмник отзывов, external_posts/replies, инструмент publish_public_reply | E15 | L3 | `SA-Agent` | M | да | T-171, T-058, T-032, T-008 |
| [T-182](T-182-zahvat-audio-v-brauzere-getusermedia-audioworkle.md) Захват аудио в браузере: getUserMedia, AudioWorklet, ресемплинг, клиент /ws/audio | E16 | L4 | `SA-UI-Compliance` | M | да | T-181, T-007 |
| [T-183](T-183-audiosessii-repliki-i-tri-rezhima-razdeleniya-sp.md) Аудиосессии, реплики и три режима разделения спикеров | E16 | L3 | `SA-Compliance` | M | да | T-181, T-180, T-046 |
| [T-185](T-185-llm-detektor-missellinga-lightning-podtverzhdeni.md) LLM-детектор мисселлинга (Lightning), подтверждение/снятие отметки, failover | E16 | L3 | `SA-Compliance` | M | да | T-183, T-184, T-047, T-049 |
| [T-186](T-186-schetchik-narushenij-mashina-sostoyanij-sessii-a.md) Счётчик нарушений, машина состояний сессии, алерт и инцидент misselling | E16 | L3 | `SA-Compliance` | M | да | T-185, T-058, T-077, T-131 |
| [T-196](T-196-avtomaticheskij-failover-po-tajmautu-i-oshibkam.md) Автоматический failover по таймауту и ошибкам LLM/STT без разрыва цепочки | E17 | L3 | `SA-Agent` | S | да | T-194, T-174, T-185 |
| [T-197](T-197-install-sh-i-compose-flagi-no-stt-stt-model-reco.md) install.sh и compose: флаги --no-stt, --stt-model, --record-cassettes, расширенный --offline, предупреждение про HTTPS | E17 | L1 | `SA-Infra` | S | да | T-003, T-181, T-194 |
| [T-209](T-209-adaptery-istochnikov-ingest-sources-rest-polling.md) Адаптеры источников ingest_sources: REST, polling-воркер, file; встроенная mock-лента /api/public/mock-social-feed | E18 | L2 | `SA-Teams` | M | — | T-207, T-178 |
| [T-210](T-210-trehklassnaya-tonalnost-sentiment-prompt-soglaso.md) Трёхклассная тональность sentiment: промпт, согласование с порогами negativity, набор sentiment_v1 и бенчмарк ≥ 80 % | E18 | L3 | `SA-Prompts` | M | да | T-059, T-060, T-129, T-207 |
| [T-211](T-211-detektor-skrytogo-negativa-few-shot-prompt-hidde.md) Детектор скрытого негатива few-shot: промпт hidden_negativity.md, объект hidden_negativity, флаги, набор hidden_negativity_v1 | E18 | L3 | `SA-Prompts` | M | — | T-210 |
| [T-212](T-212-problem-summary-problem-severity-suggested-team.md) problem_summary {problem, severity, suggested_team}: structured output, валидация ≤ 2 предложений, отображение severity ↔ criticality, набор summary_v1 | E18 | L3 | `SA-Prompts` | S | да | T-060, T-210 |
| [T-213](T-213-router-instrumenty-route-to-department-notify-cu.md) Роутер-инструменты route_to_department / notify_customer / escalate_to_manager / request_clarification, router_action, таблица escalations, политика эскалации | E18 | L3 | `SA-Agent` | L | да | T-061, T-062, T-076, T-207, T-212 |
| [T-215](T-215-taksonomiya-krasnyh-fraz-semejstvo-conduct-ruden.md) Таксономия «красных фраз»: семейство conduct (rudeness, script_violation, misinformation), политики алерта, service_scripts и проверка фактов по продуктам | E18 | L3 | `SA-Compliance` | M | да | T-184, T-185 |
| [T-216](T-216-paketnyj-analiz-transkripta-pacing-batch-transcr.md) Пакетный анализ транскрипта (pacing=batch): transcript_report, рекомендации руководителю, алерты immediate, отправка на /manager и в лог | E18 | L3 | `SA-Compliance` | M | да | T-208, T-215, T-186 |

### Волна 4 — Замыкание петли: HITL, подарки, карточка, «Под капотом», лендинг/бот, экономика «Факт»; v1.3 — экраны /feed, /compliance, /manager, меню демонстратора, сценарии 8–9, «Надиктовать»

| Карточка | Эпик | Слой | Субагент | Оценка | Демо-мин. | Зависит от |
|---|---|---|---|---|---|---|
| [T-038](T-038-dvizhok-scenariev-yaml-i-7-demo-scenariev.md) Движок сценариев YAML и 7 демо-сценариев | E3 | L2 | `SA-Scenarios` | L | — | T-034, T-036, T-037, T-040, T-056, T-161 |
| [T-039](T-039-proaktivnaya-vetka-sboj-uvedomleniya-zatronutym.md) Проактивная ветка: сбой → уведомления затронутым клиентам до жалоб | E3 | L3 | `SA-Agent` | M | — | T-034, T-056, T-062 |
| [T-063](T-063-uzly-followup-monitor-verify-close-gift-i-otlozh.md) Узлы followup_monitor, verify, close, gift и отложенные обращения | E5 | L3 | `SA-Agent` | M | — | T-062, T-036, T-078 |
| [T-064](T-064-deduplikaciya-i-massovye-incidenty.md) Дедупликация и массовые инциденты | E5 | L3 | `SA-Agent` | S | — | T-061, T-039 |
| [T-066](T-066-versionirovanie-promptov-i-gate-na-lite-benchmar.md) Версионирование промптов и gate на lite-бенчмарке | E5 | L3 | `SA-Prompts` | S | — | T-060, T-061, T-129 |
| [T-067](T-067-zhyuri-rezhim-ruchnoj-vvod-signala-i-sravnenie-s.md) Жюри-режим: ручной ввод сигнала и сравнение с правилами | E5 | L3 | `SA-Agent` | M | — | T-062, T-065, T-049 |
| [T-078](T-078-podarki-raschet-zadachi-vydacha-posle-podtverzhd.md) Подарки: расчёт, задачи, выдача после подтверждения услуги | E6 | L3 | `SA-Agent` | M | да | T-058, T-061, T-015, T-077 |
| [T-079](T-079-ui-ocheredi-hitl-i-kartochki-resheniya.md) UI очереди HITL и карточки решения | E6 | L4 | `SA-UI-Workspace` | M | — | T-077, T-086 |
| [T-080](T-080-ui-zadach-i-podarkov.md) UI задач и подарков | E6 | L4 | `SA-UI-Workspace` | S | — | T-078, T-086 |
| [T-090](T-090-kartochka-incidenta.md) Карточка инцидента | E7 | L4 | `SA-UI-Workspace` | L | да | T-089, T-091, T-131, T-063 |
| [T-092](T-092-vkladki-otlozhennye-komandy-uvedomleniya.md) Вкладки «Отложенные», «Команды», «Уведомления» | E7 | L4 | `SA-UI-Workspace` | M | — | T-086, T-063, T-037 |
| [T-093](T-093-dashbord-kpi-i-blok-ekonomiki.md) Дашборд KPI и блок экономики | E7 | L4 | `SA-UI-Workspace` | M | — | T-086, T-132 |
| [T-094](T-094-vkladka-zapuski-istoriya-sravnenie-sbros-k-basel.md) Вкладка «Запуски»: история, сравнение, сброс к baseline, экспорт | E7 | L4 | `SA-UI-Workspace` | M | да | T-086, T-040, T-042, T-041 |
| [T-106](T-106-zhivaya-trassirovka-agenta.md) Живая трассировка агента | E8 | L4 | `SA-UI-Engine` | L | да | T-065, T-007, T-008 |
| [T-107](T-107-graf-langgraph-s-podsvetkoj-uzla-i-graf-suschnos.md) Граф LangGraph с подсветкой узла и граф сущностей | E8 | L4 | `SA-UI-Engine` | M | да | T-106, T-056 |
| [T-108](T-108-lenta-izmenenij-bd-schetchiki-tablic-prosmotr-st.md) Лента изменений БД, счётчики таблиц, просмотр строк | E8 | L4 | `SA-UI-Engine` | M | да | T-005, T-008, T-007 |
| [T-119](T-119-lending-potencialnogo-klienta-antibot-proverka-q.md) Лендинг потенциального клиента, антибот-проверка, QR | E9 | L4 | `SA-Landing` | M | да | T-007, T-062 |
| [T-120](T-120-stranica-trekinga-obrascheniya-i-dopolnenie.md) Страница трекинга обращения и дополнение | E9 | L4 | `SA-Landing` | M | да | T-119, T-063 |
| [T-121](T-121-telegram-bot-cxpulsecontrolbot-aiogram.md) Telegram-бот @CXPulseControlBot (aiogram) | E9 | L3 | `SA-TgBot` | L | — | T-062, T-120 |
| [T-130](T-130-ui-benchmarkov.md) UI бенчмарков | E10 | L3 | `SA-Bench` | M | — | T-129, T-007 |
| [T-133](T-133-ekran-kalkulyator-poter-dopuscheniya-v-stile-biz.md) Экран «Калькулятор потерь» (допущения) в стиле бизнес-команды | E10 | L2 | `SA-Economics` | M | — | T-131, T-007 |
| [T-165](T-165-kalibrovka-koefficientov-uderzhaniya-po-faktam-s.md) Калибровка коэффициентов удержания по фактам симуляции | E14 | L2 | `SA-Economics` | S | — | T-161, T-131 |
| [T-166](T-166-vkladka-kalkulyatora-fakt-po-simulyacii-api-ui-e.md) Вкладка калькулятора «Факт по симуляции»: API, UI, экспорт | E14 | L2 | `SA-Economics` | L | — | T-165, T-164, T-133 |
| [T-177](T-177-ekran-feed-emulyator-lenty-ploschadki-vidzhet-ab.md) Экран /feed: эмулятор ленты площадки, виджет «АБС (эмуляция)», панель Log | E15 | L4 | `SA-UI-Feed` | L | да | T-176, T-007, T-008, T-201 |
| [T-179](T-179-scenarij-8-komissiya-za-qr-oplatu-i-publichnyj-o.md) Сценарий 8 «Комиссия за QR-оплату и публичный отзыв»: YAML, автотест, замер латентности | E15 | L5 | `SA-QA` | M | да | T-174, T-175, T-176, T-038, T-198 |
| [T-187](T-187-ekran-compliance-split-screen-transkribacii-sche.md) Экран /compliance: split-screen транскрибации, счётчик, профиль менеджера, панель Log | E16 | L4 | `SA-UI-Compliance` | L | да | T-182, T-183, T-186, T-201 |
| [T-188](T-188-ekran-manager-emulyator-plansheta-i-smart-chasov.md) Экран /manager: эмулятор планшета и смарт-часов руководителя, ack → HITL | E16 | L4 | `SA-UI-Compliance` | M | да | T-186, T-007 |
| [T-189](T-189-alert-o-missellinge-v-telegram-rukovoditelyu.md) Алерт о мисселлинге в Telegram руководителю | E16 | L3 | `SA-TgBot` | S | — | T-186, T-121 |
| [T-191](T-191-benchmark-detektora-missellinga-i-stt-ranner-met.md) Бенчмарк детектора мисселлинга и STT: раннер, метрики, UI | E16 | L3 | `SA-Bench` | M | — | T-185, T-190, T-129, T-130 |
| [T-192](T-192-scenarij-9-misselling-v-otdelenii-yaml-avtotest.md) Сценарий 9 «Мисселлинг в отделении»: YAML, автотест с файла и транскрипта | E16 | L5 | `SA-QA` | M | да | T-186, T-190, T-038, T-198 |
| [T-195](T-195-menyu-demonstratora-skrytaya-knopka-statusy-prov.md) Меню демонстратора: скрытая кнопка, статусы провайдеров, переключатели, запуск предзаписанных входов, QR | E17 | L4 | `SA-UI-Workspace` | M | да | T-194, T-086, T-094, T-040 |
| [T-198](T-198-kassety-scenariev-8-9-i-avtotesty-na-nih-procedu.md) Кассеты сценариев 8–9 и автотесты на них; процедура перезаписи при смене промптов | E17 | L1 | `SA-LLM` | S | да | T-194, T-174, T-185, T-066 |
| [T-201](T-201-panel-log-debug-kak-obschij-komponent-demo-ekran.md) Панель «Log/Debug» как общий компонент демо-экранов | E8 | L4 | `SA-UI-Engine` | M | да | T-106, T-008, T-065 |
| [T-202](T-202-ekonomika-fee-refund-i-misselling-stroka-effekta.md) Экономика fee_refund и misselling, строка эффекта, настройка misselling_case_cost_rub | E10 | L2 | `SA-Economics` | S | — | T-131, T-171, T-186 |
| [T-206](T-206-nadiktovat-zhalobu-voiceinput-v-rezhime-pokaza-i.md) «Надиктовать жалобу»: VoiceInput в режиме показа и на лендинге, signals.origin=voice_input, шаг STT в трассировке | E9 | L4 | `SA-UI-Compliance` | S | да | T-182, T-067, T-119 |
| [T-214](T-214-tiketnica-v-tickets-get-api-tickets-vkladka-tike.md) Тикетница: v_tickets, GET /api/tickets, вкладка «Тикеты» и фильтр «Эскалации» в HITL, экспорт цепочки решений decision-chain | E18 | L4 | `SA-UI-Workspace` | M | да | T-213, T-089, T-106 |
| [T-217](T-217-ui-vkladka-transkripty-na-compliance-zagruzka-sp.md) UI: вкладка «Транскрипты» на /compliance (загрузка, список, отчёт с подсветкой семейств), раздел «Отчёты по транскриптам» на /manager | E18 | L4 | `SA-UI-Compliance` | M | да | T-216, T-187, T-188 |
| [T-218](T-218-karta-sloj-zony-zelenaya-zheltaya-krasnaya-po-v.md) Карта: слой «Зоны» (зелёная/жёлтая/красная) по v_map_zones, настройка порогов, счётчик «без гео», живой тикер экономики | E18 | L4 | `SA-Map` | M | да | T-088, T-093, T-132, T-207, T-215 |
| [T-220](T-220-scenarii-10-transkript-roznichnogo-dialoga-i-11.md) Сценарии 10 «Транскрипт розничного диалога» и 11 «Сарказм → уточнение → эскалация»: YAML, автотесты, кассеты, блок D демо-скрипта | E18 | L5 | `SA-QA` | M | да | T-216, T-213, T-214, T-217, T-218, T-209, T-198 |

### Волна 5 — Тесты, i18n, документация, панели сравнения

| Карточка | Эпик | Слой | Субагент | Оценка | Демо-мин. | Зависит от |
|---|---|---|---|---|---|---|
| [T-109](T-109-panel-ii-protiv-pravil.md) Панель «ИИ против правил» | E8 | L4 | `SA-UI-Engine` | S | — | T-067, T-106 |
| [T-110](T-110-dialog-agent-dvojnik-i-sostoyanie-klienta.md) Диалог «агент ↔ двойник» и состояние клиента | E8 | L4 | `SA-UI-Engine` | S | — | T-163, T-106 |
| [T-122](T-122-qr-kod-bota-zhyuri-rezhim-i-instrukcii-dlya-fina.md) QR-код бота, жюри-режим и инструкции для финала | E9 | L3 | `SA-TgBot` | S | — | T-121, T-086 |
| [T-142](T-142-avtotesty-7-demo-scenariev.md) Автотесты 7 демо-сценариев | E11 | L5 | `SA-QA` | M | да | T-038, T-141 |
| [T-143](T-143-playwright-smouk-i-vizualnaya-regressiya.md) Playwright-смоук и визуальная регрессия | E11 | L5 | `SA-QA` | M | — | T-010, T-086, T-090, T-106, T-119 |
| [T-144](T-144-proverka-proizvoditelnosti-profilya-demo.md) Проверка производительности профиля demo | E11 | L5 | `SA-QA` | S | — | T-033, T-037, T-087, T-008 |
| [T-145](T-145-ci-konvejer-polnogo-cikla.md) CI-конвейер полного цикла | E11 | L5 | `SA-QA` | S | — | T-001, T-141, T-143 |
| [T-146](T-146-testy-izolyacii-zapuskov-i-vozobnovleniya.md) Тесты изоляции запусков и возобновления | E11 | L5 | `SA-QA` | M | — | T-142, T-040, T-041, T-042 |
| [T-151](T-151-readme-i-demo-skript.md) README и демо-скрипт | E12 | L1 | `SA-Docs` | M | да | T-003, T-038, T-122 |
| [T-152](T-152-licenses-md-i-istochniki-dannyh.md) LICENSES.md и источники данных | E12 | L1 | `SA-Docs` | S | — | T-001, T-011 |
| [T-156](T-156-polnye-slovari-ru-en-i-proverka-i18n.md) Полные словари ru/en и проверка i18n | E13 | L1 | `SA-i18n` | M | — | T-010, T-086, T-090, T-106, T-119, T-130, T-133 |
| [T-157](T-157-yazyk-kommunikacij-s-klientom-i-en-shablony.md) Язык коммуникаций с клиентом и en-шаблоны | E13 | L1 | `SA-i18n` | S | — | T-015, T-062, T-121 |
| [T-167](T-167-statisticheskie-testy-modeli-povedeniya.md) Статистические тесты модели поведения | E14 | L5 | `SA-QA` | S | — | T-161, T-162, T-163, T-164 |
| [T-193](T-193-opcionalnye-stt-provajdery-browser-web-speech-sa.md) Опциональные STT-провайдеры: browser (Web Speech), SaluteSpeech, OpenAI-совместимый аудио-сервер | E16 | L3 | `SA-STT` | S | — | T-181, T-182 |
| [T-203](T-203-lokalizaciya-ekranov-v1-3-feed-compliance-manage.md) Локализация экранов v1.3 (feed, compliance, manager, демо-меню) и тексты алертов/публичных ответов | E13 | L1 | `SA-i18n` | S | — | T-177, T-187, T-188, T-195, T-156 |
| [T-204](T-204-demo-skript-7-8-i-3-5-minut-readme-razdelov-zhiv.md) Демо-скрипт 7–8 и 3–5 минут, README разделов «Живые контуры», «Демо без интернета», «Микрофон и HTTPS» | E12 | L1 | `SA-Docs` | S | — | T-151, T-179, T-192, T-195 |

### Волна 6 — Защита

| Карточка | Эпик | Слой | Субагент | Оценка | Демо-мин. | Зависит от |
|---|---|---|---|---|---|---|
| [T-154](T-154-materialy-zaschity-tezisy-slajdy-opory-otvety-na.md) Материалы защиты: тезисы, слайды-опоры, ответы на вопросы жюри | E12 | L1 | `SA-Docs` | M | — | T-151, T-093, T-130 |

## По слоям (кто ведёт — docs/TEAM-SPLIT.md)

| Слой | Карточек | Из них в демо-минимуме | Объём (чел.-дни по оценкам) | Объём демо-минимума | Пик по волнам |
|---|---|---|---|---|---|
| `L1` Базис | 36 | 29 | 46 | 39 | в1: 14, в2: 12, в3: 2, в4: 1, в5: 6, в6: 1 |
| `L2` Симулятор и данные | 32 | 24 | 62 | 47 | в2: 17, в3: 10, в4: 5 |
| `L3` Агент и контуры | 42 | 30 | 74 | 58 | в2: 8, в3: 22, в4: 10, в5: 2 |
| `L4` Фронт | 30 | 24 | 54 | 47 | в1: 1, в2: 2, в3: 5, в4: 20, в5: 2 |
| `L5` Качество | 10 | 5 | 13 | 8 | в1: 1, в4: 3, в5: 6 |

### `L1` Базис

- Волна 1: [T-001](T-001-skelet-repozitoriya-makefile-env-example-pre-com.md), [T-002](T-002-docker-compose-i-dockerfile-y-postgres-backend-f.md), [T-004](T-004-karkas-fastapi-konfig-logirovanie-oshibki-health.md), [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-006](T-006-sync-contracts-generaciya-enums-pydantic-shem-ts.md), [T-011](T-011-spravochnik-subektov-i-gorodov-rf-svg-karta.md), [T-012](T-012-segmenty-psihotipy-doli-psihotipov-po-segmentam.md), [T-013](T-013-produkty-sistemy-komandy-kanaly.md), [T-014](T-014-kody-oshibok-tipy-signalov-pravila-marshrutizaci.md), [T-015](T-015-shablony-uvedomlenij-spravochnik-podarkov-stavki.md), [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md), [T-047](T-047-gigachat-provajder-s-pulom-klyuchej-i-uchetom-to.md), [T-048](T-048-openai-sovmestimyj-provajder-openrouter-i-lokaln.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md)
- Волна 2: [T-003](T-003-install-sh-ustanovka-odnoj-komandoj.md), [T-008](T-008-realtime-listen-notify-websocket-hab.md), [T-009](T-009-api-mastera-nastrojki-i-proverok-podklyucheniya.md), [T-021](T-021-zolotoj-nabor-benchmarka-golden-v1-i-lite-v1.md), [T-050](T-050-rate-limiter-byudzhety-fallback-i-maskirovanie-s.md), [T-051](T-051-api-i-ui-profilej-llm-i-klyuchej.md), [T-153](T-153-nachalnyj-nabor-adr.md), [T-194](T-194-provajder-replay-kassety-zapisannyh-otvetov-mode.md), [T-199](T-199-migraciya-0002-primenenie-modeli-sqlalchemy-i-pe.md), [T-200](T-200-openapi-1-3-i-json-shemy-v-kode-routery-zaglushk.md), [T-205](T-205-agents-md-v1-3-pravila-14-15-podsistemy-6-7-6-9.md) (откл.), [T-221](T-221-migraciya-0003-i-openapi-1-4-v-kode-modeli-sqlal.md)
- Волна 3: [T-022](T-022-testy-dannyh-no-pii-pokrytie-idempotentnost-proi.md), [T-197](T-197-install-sh-i-compose-flagi-no-stt-stt-model-reco.md)
- Волна 4: [T-198](T-198-kassety-scenariev-8-9-i-avtotesty-na-nih-procedu.md)
- Волна 5: [T-151](T-151-readme-i-demo-skript.md), [T-152](T-152-licenses-md-i-istochniki-dannyh.md) (откл.), [T-156](T-156-polnye-slovari-ru-en-i-proverka-i18n.md) (откл.), [T-157](T-157-yazyk-kommunikacij-s-klientom-i-en-shablony.md) (откл.), [T-203](T-203-lokalizaciya-ekranov-v1-3-feed-compliance-manage.md) (откл.), [T-204](T-204-demo-skript-7-8-i-3-5-minut-readme-razdelov-zhiv.md) (откл.)
- Волна 6: [T-154](T-154-materialy-zaschity-tezisy-slajdy-opory-otvety-na.md) (откл.)

### `L2` Симулятор и данные

- Волна 2: [T-016](T-016-generator-klientov-profili-lite-demo-stress.md), [T-017](T-017-produkty-klientov-i-14-dnej-operacij.md), [T-018](T-018-predystoriya-sboev-i-logi-sistem.md), [T-019](T-019-biblioteka-tekstov-signalov.md), [T-031](T-031-simclock-sim-state-i-upravlenie-simulyaciej.md), [T-032](T-032-shina-sobytij-simulyatora.md), [T-033](T-033-generator-operacij-v-realnom-vremeni.md), [T-034](T-034-generator-sboev-i-vosstanovlenij.md), [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md), [T-131](T-131-raschet-ekonomiki-dcltv-po-incidentu.md), [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md), [T-171](T-171-mock-abs-scheta-tarify-provodki-sid-i-invariant.md), [T-172](T-172-rules-engine-business-rules-dsl-uslovij-uzel-che.md), [T-178](T-178-korpus-publichnyh-otzyvov-i-nabor-reviews-v1.md) (откл.), [T-180](T-180-rasshirenie-zapuskov-avtosozdanie-run-kind-live.md), [T-190](T-190-dialogi-otdeleniya-nabor-misselling-v1-predzapis.md) (откл.), [T-219](T-219-korpusa-dtz-transcripts-v1-20-transkriptov-json.md)
- Волна 3: [T-020](T-020-predystoriya-signalov-incidentov-statusov-artefa.md), [T-035](T-035-generator-oshibok-klientov.md), [T-036](T-036-emulyator-komand-i-cifrovoj-sled-incidenta.md), [T-037](T-037-sla-dvizhok.md), [T-042](T-042-itogovye-metriki-zapuska-summary-i-eksport.md), [T-132](T-132-api-svodnoj-ekonomiki-i-metrik-dashborda.md), [T-162](T-162-detekciya-snizheniya-aktivnosti-molchalivyj-uhod.md), [T-163](T-163-llm-dvojniki-podsvechennyh-klientov.md), [T-164](T-164-uhod-klienta-churn-events-incident-account-closu.md), [T-209](T-209-adaptery-istochnikov-ingest-sources-rest-polling.md) (откл.)
- Волна 4: [T-038](T-038-dvizhok-scenariev-yaml-i-7-demo-scenariev.md) (откл.), [T-133](T-133-ekran-kalkulyator-poter-dopuscheniya-v-stile-biz.md) (откл.), [T-165](T-165-kalibrovka-koefficientov-uderzhaniya-po-faktam-s.md) (откл.), [T-166](T-166-vkladka-kalkulyatora-fakt-po-simulyacii-api-ui-e.md) (откл.), [T-202](T-202-ekonomika-fee-refund-i-misselling-stroka-effekta.md) (откл.)

### `L3` Агент и контуры

- Волна 2: [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md), [T-057](T-057-instrumenty-chteniya-konteksta.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md), [T-076](T-076-politiki-hitl-policies-py-i-testy.md), [T-181](T-181-sttprovider-i-vosk-vorker-s-modelyu-v-repozitori.md), [T-184](T-184-taksonomiya-missellinga-i-rule-detektor-predvari.md), [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md), [T-208](T-208-priem-transkriptov-json-txt-parsery-post-api-ing.md)
- Волна 3: [T-041](T-041-preryvanie-i-vozobnovlenie-emulyacii-vosstanovle.md), [T-059](T-059-uzly-ingest-normalize-identify-client-gather-con.md), [T-060](T-060-uzel-classify-i-prompty-v1.md), [T-061](T-061-uzel-decide-sla-marshrutizaciya-prioritet-politi.md), [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md), [T-065](T-065-trassirovka-zapuskov-i-striming-tokenov.md), [T-077](T-077-uzel-wait-human-ochered-hitl-i-vozvrat-resheniya.md), [T-129](T-129-benchmark-ranner-i-metriki.md), [T-173](T-173-matching-klienta-po-kosvennym-dannym-match-clien.md), [T-174](T-174-bystryj-put-agenta-uslovnoe-rebro-act-instant-st.md), [T-175](T-175-instrumenty-refund-fee-find-affected-clients-get.md), [T-176](T-176-priemnik-otzyvov-external-posts-replies-instrume.md), [T-183](T-183-audiosessii-repliki-i-tri-rezhima-razdeleniya-sp.md), [T-185](T-185-llm-detektor-missellinga-lightning-podtverzhdeni.md), [T-186](T-186-schetchik-narushenij-mashina-sostoyanij-sessii-a.md), [T-196](T-196-avtomaticheskij-failover-po-tajmautu-i-oshibkam.md), [T-210](T-210-trehklassnaya-tonalnost-sentiment-prompt-soglaso.md), [T-211](T-211-detektor-skrytogo-negativa-few-shot-prompt-hidde.md) (откл.), [T-212](T-212-problem-summary-problem-severity-suggested-team.md), [T-213](T-213-router-instrumenty-route-to-department-notify-cu.md), [T-215](T-215-taksonomiya-krasnyh-fraz-semejstvo-conduct-ruden.md), [T-216](T-216-paketnyj-analiz-transkripta-pacing-batch-transcr.md)
- Волна 4: [T-039](T-039-proaktivnaya-vetka-sboj-uvedomleniya-zatronutym.md) (откл.), [T-063](T-063-uzly-followup-monitor-verify-close-gift-i-otlozh.md) (откл.), [T-064](T-064-deduplikaciya-i-massovye-incidenty.md) (откл.), [T-066](T-066-versionirovanie-promptov-i-gate-na-lite-benchmar.md) (откл.), [T-067](T-067-zhyuri-rezhim-ruchnoj-vvod-signala-i-sravnenie-s.md) (откл.), [T-078](T-078-podarki-raschet-zadachi-vydacha-posle-podtverzhd.md), [T-121](T-121-telegram-bot-cxpulsecontrolbot-aiogram.md) (откл.), [T-130](T-130-ui-benchmarkov.md) (откл.), [T-189](T-189-alert-o-missellinge-v-telegram-rukovoditelyu.md) (откл.), [T-191](T-191-benchmark-detektora-missellinga-i-stt-ranner-met.md) (откл.)
- Волна 5: [T-122](T-122-qr-kod-bota-zhyuri-rezhim-i-instrukcii-dlya-fina.md) (откл.), [T-193](T-193-opcionalnye-stt-provajdery-browser-web-speech-sa.md) (откл.)

### `L4` Фронт

- Волна 1: [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md)
- Волна 2: [T-010](T-010-ui-mastera-nastrojki-9-shagov-i-ekran-nastrojki.md), [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md)
- Волна 3: [T-087](T-087-lenta-signalov.md), [T-088](T-088-teplovaya-karta-rf-s-drill-down-do-gorodov.md), [T-089](T-089-doska-i-tablica-incidentov-s-indikatorami-sla.md), [T-091](T-091-klient-360.md), [T-182](T-182-zahvat-audio-v-brauzere-getusermedia-audioworkle.md)
- Волна 4: [T-079](T-079-ui-ocheredi-hitl-i-kartochki-resheniya.md) (откл.), [T-080](T-080-ui-zadach-i-podarkov.md) (откл.), [T-090](T-090-kartochka-incidenta.md), [T-092](T-092-vkladki-otlozhennye-komandy-uvedomleniya.md) (откл.), [T-093](T-093-dashbord-kpi-i-blok-ekonomiki.md) (откл.), [T-094](T-094-vkladka-zapuski-istoriya-sravnenie-sbros-k-basel.md), [T-106](T-106-zhivaya-trassirovka-agenta.md), [T-107](T-107-graf-langgraph-s-podsvetkoj-uzla-i-graf-suschnos.md), [T-108](T-108-lenta-izmenenij-bd-schetchiki-tablic-prosmotr-st.md), [T-119](T-119-lending-potencialnogo-klienta-antibot-proverka-q.md), [T-120](T-120-stranica-trekinga-obrascheniya-i-dopolnenie.md), [T-177](T-177-ekran-feed-emulyator-lenty-ploschadki-vidzhet-ab.md), [T-187](T-187-ekran-compliance-split-screen-transkribacii-sche.md), [T-188](T-188-ekran-manager-emulyator-plansheta-i-smart-chasov.md), [T-195](T-195-menyu-demonstratora-skrytaya-knopka-statusy-prov.md), [T-201](T-201-panel-log-debug-kak-obschij-komponent-demo-ekran.md), [T-206](T-206-nadiktovat-zhalobu-voiceinput-v-rezhime-pokaza-i.md), [T-214](T-214-tiketnica-v-tickets-get-api-tickets-vkladka-tike.md), [T-217](T-217-ui-vkladka-transkripty-na-compliance-zagruzka-sp.md), [T-218](T-218-karta-sloj-zony-zelenaya-zheltaya-krasnaya-po-v.md)
- Волна 5: [T-109](T-109-panel-ii-protiv-pravil.md) (откл.), [T-110](T-110-dialog-agent-dvojnik-i-sostoyanie-klienta.md) (откл.)

### `L5` Качество

- Волна 1: [T-141](T-141-testovaya-infrastruktura-backend.md)
- Волна 4: [T-179](T-179-scenarij-8-komissiya-za-qr-oplatu-i-publichnyj-o.md), [T-192](T-192-scenarij-9-misselling-v-otdelenii-yaml-avtotest.md), [T-220](T-220-scenarii-10-transkript-roznichnogo-dialoga-i-11.md)
- Волна 5: [T-142](T-142-avtotesty-7-demo-scenariev.md), [T-143](T-143-playwright-smouk-i-vizualnaya-regressiya.md) (откл.), [T-144](T-144-proverka-proizvoditelnosti-profilya-demo.md) (откл.), [T-145](T-145-ci-konvejer-polnogo-cikla.md) (откл.), [T-146](T-146-testy-izolyacii-zapuskov-i-vozobnovleniya.md) (откл.), [T-167](T-167-statisticheskie-testy-modeli-povedeniya.md) (откл.)

## По эпикам

- **E1 Каркас, БД, установка** — 12 карточек: [T-001](T-001-skelet-repozitoriya-makefile-env-example-pre-com.md), [T-002](T-002-docker-compose-i-dockerfile-y-postgres-backend-f.md), [T-003](T-003-install-sh-ustanovka-odnoj-komandoj.md), [T-004](T-004-karkas-fastapi-konfig-logirovanie-oshibki-health.md), [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-006](T-006-sync-contracts-generaciya-enums-pydantic-shem-ts.md), [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md), [T-008](T-008-realtime-listen-notify-websocket-hab.md), [T-009](T-009-api-mastera-nastrojki-i-proverok-podklyucheniya.md), [T-010](T-010-ui-mastera-nastrojki-9-shagov-i-ekran-nastrojki.md), [T-199](T-199-migraciya-0002-primenenie-modeli-sqlalchemy-i-pe.md), [T-200](T-200-openapi-1-3-i-json-shemy-v-kode-routery-zaglushk.md). Субагенты: `SA-DB`, `SA-Infra`, `SA-UI-Workspace`.
- **E2 Справочники и генераторы данных** — 12 карточек: [T-011](T-011-spravochnik-subektov-i-gorodov-rf-svg-karta.md), [T-012](T-012-segmenty-psihotipy-doli-psihotipov-po-segmentam.md), [T-013](T-013-produkty-sistemy-komandy-kanaly.md), [T-014](T-014-kody-oshibok-tipy-signalov-pravila-marshrutizaci.md), [T-015](T-015-shablony-uvedomlenij-spravochnik-podarkov-stavki.md), [T-016](T-016-generator-klientov-profili-lite-demo-stress.md), [T-017](T-017-produkty-klientov-i-14-dnej-operacij.md), [T-018](T-018-predystoriya-sboev-i-logi-sistem.md), [T-019](T-019-biblioteka-tekstov-signalov.md), [T-020](T-020-predystoriya-signalov-incidentov-statusov-artefa.md), [T-021](T-021-zolotoj-nabor-benchmarka-golden-v1-i-lite-v1.md), [T-022](T-022-testy-dannyh-no-pii-pokrytie-idempotentnost-proi.md). Субагенты: `SA-Clients`, `SA-DB`, `SA-Logs`, `SA-Refs`, `SA-Signals`.
- **E3 Симулятор банка, команды, SLA** — 12 карточек: [T-031](T-031-simclock-sim-state-i-upravlenie-simulyaciej.md), [T-032](T-032-shina-sobytij-simulyatora.md), [T-033](T-033-generator-operacij-v-realnom-vremeni.md), [T-034](T-034-generator-sboev-i-vosstanovlenij.md), [T-035](T-035-generator-oshibok-klientov.md), [T-036](T-036-emulyator-komand-i-cifrovoj-sled-incidenta.md), [T-037](T-037-sla-dvizhok.md), [T-038](T-038-dvizhok-scenariev-yaml-i-7-demo-scenariev.md), [T-039](T-039-proaktivnaya-vetka-sboj-uvedomleniya-zatronutym.md), [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md), [T-041](T-041-preryvanie-i-vozobnovlenie-emulyacii-vosstanovle.md), [T-042](T-042-itogovye-metriki-zapuska-summary-i-eksport.md). Субагенты: `SA-Agent`, `SA-Economics`, `SA-Logs`, `SA-Scenarios`, `SA-Teams`.
- **E4 LLM-слой** — 6 карточек: [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md), [T-047](T-047-gigachat-provajder-s-pulom-klyuchej-i-uchetom-to.md), [T-048](T-048-openai-sovmestimyj-provajder-openrouter-i-lokaln.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md), [T-050](T-050-rate-limiter-byudzhety-fallback-i-maskirovanie-s.md), [T-051](T-051-api-i-ui-profilej-llm-i-klyuchej.md). Субагенты: `SA-LLM`.
- **E5 Агент LangGraph** — 12 карточек: [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md), [T-057](T-057-instrumenty-chteniya-konteksta.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md), [T-059](T-059-uzly-ingest-normalize-identify-client-gather-con.md), [T-060](T-060-uzel-classify-i-prompty-v1.md), [T-061](T-061-uzel-decide-sla-marshrutizaciya-prioritet-politi.md), [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md), [T-063](T-063-uzly-followup-monitor-verify-close-gift-i-otlozh.md), [T-064](T-064-deduplikaciya-i-massovye-incidenty.md), [T-065](T-065-trassirovka-zapuskov-i-striming-tokenov.md), [T-066](T-066-versionirovanie-promptov-i-gate-na-lite-benchmar.md), [T-067](T-067-zhyuri-rezhim-ruchnoj-vvod-signala-i-sravnenie-s.md). Субагенты: `SA-Agent`, `SA-Prompts`.
- **E6 HITL и подарки** — 5 карточек: [T-076](T-076-politiki-hitl-policies-py-i-testy.md), [T-077](T-077-uzel-wait-human-ochered-hitl-i-vozvrat-resheniya.md), [T-078](T-078-podarki-raschet-zadachi-vydacha-posle-podtverzhd.md), [T-079](T-079-ui-ocheredi-hitl-i-kartochki-resheniya.md), [T-080](T-080-ui-zadach-i-podarkov.md). Субагенты: `SA-Agent`, `SA-UI-Workspace`.
- **E7 Рабочее место CX** — 9 карточек: [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md), [T-087](T-087-lenta-signalov.md), [T-088](T-088-teplovaya-karta-rf-s-drill-down-do-gorodov.md), [T-089](T-089-doska-i-tablica-incidentov-s-indikatorami-sla.md), [T-090](T-090-kartochka-incidenta.md), [T-091](T-091-klient-360.md), [T-092](T-092-vkladki-otlozhennye-komandy-uvedomleniya.md), [T-093](T-093-dashbord-kpi-i-blok-ekonomiki.md), [T-094](T-094-vkladka-zapuski-istoriya-sravnenie-sbros-k-basel.md). Субагенты: `SA-Map`, `SA-UI-Workspace`.
- **E8 «Под капотом»** — 6 карточек: [T-106](T-106-zhivaya-trassirovka-agenta.md), [T-107](T-107-graf-langgraph-s-podsvetkoj-uzla-i-graf-suschnos.md), [T-108](T-108-lenta-izmenenij-bd-schetchiki-tablic-prosmotr-st.md), [T-109](T-109-panel-ii-protiv-pravil.md), [T-110](T-110-dialog-agent-dvojnik-i-sostoyanie-klienta.md), [T-201](T-201-panel-log-debug-kak-obschij-komponent-demo-ekran.md). Субагенты: `SA-UI-Engine`.
- **E9 Лендинг, трекинг, Telegram-бот** — 5 карточек: [T-119](T-119-lending-potencialnogo-klienta-antibot-proverka-q.md), [T-120](T-120-stranica-trekinga-obrascheniya-i-dopolnenie.md), [T-121](T-121-telegram-bot-cxpulsecontrolbot-aiogram.md), [T-122](T-122-qr-kod-bota-zhyuri-rezhim-i-instrukcii-dlya-fina.md), [T-206](T-206-nadiktovat-zhalobu-voiceinput-v-rezhime-pokaza-i.md). Субагенты: `SA-Landing`, `SA-TgBot`, `SA-UI-Compliance`.
- **E10 Бенчмарки и экономика** — 6 карточек: [T-129](T-129-benchmark-ranner-i-metriki.md), [T-130](T-130-ui-benchmarkov.md), [T-131](T-131-raschet-ekonomiki-dcltv-po-incidentu.md), [T-132](T-132-api-svodnoj-ekonomiki-i-metrik-dashborda.md), [T-133](T-133-ekran-kalkulyator-poter-dopuscheniya-v-stile-biz.md), [T-202](T-202-ekonomika-fee-refund-i-misselling-stroka-effekta.md). Субагенты: `SA-Bench`, `SA-Economics`.
- **E11 Сценарии и тесты** — 6 карточек: [T-141](T-141-testovaya-infrastruktura-backend.md), [T-142](T-142-avtotesty-7-demo-scenariev.md), [T-143](T-143-playwright-smouk-i-vizualnaya-regressiya.md), [T-144](T-144-proverka-proizvoditelnosti-profilya-demo.md), [T-145](T-145-ci-konvejer-polnogo-cikla.md), [T-146](T-146-testy-izolyacii-zapuskov-i-vozobnovleniya.md). Субагенты: `SA-QA`.
- **E12 Документация и защита** — 6 карточек: [T-151](T-151-readme-i-demo-skript.md), [T-152](T-152-licenses-md-i-istochniki-dannyh.md), [T-153](T-153-nachalnyj-nabor-adr.md), [T-154](T-154-materialy-zaschity-tezisy-slajdy-opory-otvety-na.md), [T-204](T-204-demo-skript-7-8-i-3-5-minut-readme-razdelov-zhiv.md), [T-205](T-205-agents-md-v1-3-pravila-14-15-podsistemy-6-7-6-9.md). Субагенты: `SA-Docs`.
- **E13 Локализация** — 3 карточек: [T-156](T-156-polnye-slovari-ru-en-i-proverka-i18n.md), [T-157](T-157-yazyk-kommunikacij-s-klientom-i-en-shablony.md), [T-203](T-203-lokalizaciya-ekranov-v1-3-feed-compliance-manage.md). Субагенты: `SA-i18n`.
- **E14 Поведение клиентов и калькулятор «Факт»** — 7 карточек: [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md), [T-162](T-162-detekciya-snizheniya-aktivnosti-molchalivyj-uhod.md), [T-163](T-163-llm-dvojniki-podsvechennyh-klientov.md), [T-164](T-164-uhod-klienta-churn-events-incident-account-closu.md), [T-165](T-165-kalibrovka-koefficientov-uderzhaniya-po-faktam-s.md), [T-166](T-166-vkladka-kalkulyatora-fakt-po-simulyacii-api-ui-e.md), [T-167](T-167-statisticheskie-testy-modeli-povedeniya.md). Субагенты: `SA-Behavior`, `SA-Economics`, `SA-QA`.
- **E15 Внешние площадки и автономный возврат [BRD]** — 10 карточек: [T-171](T-171-mock-abs-scheta-tarify-provodki-sid-i-invariant.md), [T-172](T-172-rules-engine-business-rules-dsl-uslovij-uzel-che.md), [T-173](T-173-matching-klienta-po-kosvennym-dannym-match-clien.md), [T-174](T-174-bystryj-put-agenta-uslovnoe-rebro-act-instant-st.md), [T-175](T-175-instrumenty-refund-fee-find-affected-clients-get.md), [T-176](T-176-priemnik-otzyvov-external-posts-replies-instrume.md), [T-177](T-177-ekran-feed-emulyator-lenty-ploschadki-vidzhet-ab.md), [T-178](T-178-korpus-publichnyh-otzyvov-i-nabor-reviews-v1.md), [T-179](T-179-scenarij-8-komissiya-za-qr-oplatu-i-publichnyj-o.md), [T-180](T-180-rasshirenie-zapuskov-avtosozdanie-run-kind-live.md). Субагенты: `SA-ABS`, `SA-Agent`, `SA-QA`, `SA-Signals`, `SA-Teams`, `SA-UI-Feed`.
- **E16 Аудиомониторинг отделения и мисселлинг [BRD]** — 13 карточек: [T-181](T-181-sttprovider-i-vosk-vorker-s-modelyu-v-repozitori.md), [T-182](T-182-zahvat-audio-v-brauzere-getusermedia-audioworkle.md), [T-183](T-183-audiosessii-repliki-i-tri-rezhima-razdeleniya-sp.md), [T-184](T-184-taksonomiya-missellinga-i-rule-detektor-predvari.md), [T-185](T-185-llm-detektor-missellinga-lightning-podtverzhdeni.md), [T-186](T-186-schetchik-narushenij-mashina-sostoyanij-sessii-a.md), [T-187](T-187-ekran-compliance-split-screen-transkribacii-sche.md), [T-188](T-188-ekran-manager-emulyator-plansheta-i-smart-chasov.md), [T-189](T-189-alert-o-missellinge-v-telegram-rukovoditelyu.md), [T-190](T-190-dialogi-otdeleniya-nabor-misselling-v1-predzapis.md), [T-191](T-191-benchmark-detektora-missellinga-i-stt-ranner-met.md), [T-192](T-192-scenarij-9-misselling-v-otdelenii-yaml-avtotest.md), [T-193](T-193-opcionalnye-stt-provajdery-browser-web-speech-sa.md). Субагенты: `SA-Bench`, `SA-Compliance`, `SA-QA`, `SA-STT`, `SA-Signals`, `SA-TgBot`, `SA-UI-Compliance`.
- **E17 Режим подстраховки демо [BRD]** — 5 карточек: [T-194](T-194-provajder-replay-kassety-zapisannyh-otvetov-mode.md), [T-195](T-195-menyu-demonstratora-skrytaya-knopka-statusy-prov.md), [T-196](T-196-avtomaticheskij-failover-po-tajmautu-i-oshibkam.md), [T-197](T-197-install-sh-i-compose-flagi-no-stt-stt-model-reco.md), [T-198](T-198-kassety-scenariev-8-9-i-avtotesty-na-nih-procedu.md). Субагенты: `SA-Agent`, `SA-Infra`, `SA-LLM`, `SA-UI-Workspace`.
- **E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ]** — 15 карточек: [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md), [T-208](T-208-priem-transkriptov-json-txt-parsery-post-api-ing.md), [T-209](T-209-adaptery-istochnikov-ingest-sources-rest-polling.md), [T-210](T-210-trehklassnaya-tonalnost-sentiment-prompt-soglaso.md), [T-211](T-211-detektor-skrytogo-negativa-few-shot-prompt-hidde.md), [T-212](T-212-problem-summary-problem-severity-suggested-team.md), [T-213](T-213-router-instrumenty-route-to-department-notify-cu.md), [T-214](T-214-tiketnica-v-tickets-get-api-tickets-vkladka-tike.md), [T-215](T-215-taksonomiya-krasnyh-fraz-semejstvo-conduct-ruden.md), [T-216](T-216-paketnyj-analiz-transkripta-pacing-batch-transcr.md), [T-217](T-217-ui-vkladka-transkripty-na-compliance-zagruzka-sp.md), [T-218](T-218-karta-sloj-zony-zelenaya-zheltaya-krasnaya-po-v.md), [T-219](T-219-korpusa-dtz-transcripts-v1-20-transkriptov-json.md), [T-220](T-220-scenarii-10-transkript-roznichnogo-dialoga-i-11.md), [T-221](T-221-migraciya-0003-i-openapi-1-4-v-kode-modeli-sqlal.md). Субагенты: `SA-Agent`, `SA-Compliance`, `SA-DB`, `SA-Map`, `SA-Prompts`, `SA-QA`, `SA-Signals`, `SA-Teams`, `SA-UI-Compliance`, `SA-UI-Workspace`.

## Граф зависимостей (критический путь выделен порядком волн)

```mermaid
graph LR
  subgraph E1[E1 Каркас, БД, установка]
    T001[T-001]
    T002[T-002]
    T003[T-003]
    T004[T-004]
    T005[T-005]
    T006[T-006]
    T007[T-007]
    T008[T-008]
    T009[T-009]
    T010[T-010]
    T199[T-199]
    T200[T-200]
  end
  subgraph E2[E2 Справочники и генераторы данных]
    T011[T-011]
    T012[T-012]
    T013[T-013]
    T014[T-014]
    T015[T-015]
    T016[T-016]
    T017[T-017]
    T018[T-018]
    T019[T-019]
    T020[T-020]
    T021[T-021]
    T022[T-022]
  end
  subgraph E3[E3 Симулятор банка, команды, SLA]
    T031[T-031]
    T032[T-032]
    T033[T-033]
    T034[T-034]
    T035[T-035]
    T036[T-036]
    T037[T-037]
    T038[T-038]
    T039[T-039]
    T040[T-040]
    T041[T-041]
    T042[T-042]
  end
  subgraph E4[E4 LLM-слой]
    T046[T-046]
    T047[T-047]
    T048[T-048]
    T049[T-049]
    T050[T-050]
    T051[T-051]
  end
  subgraph E5[E5 Агент LangGraph]
    T056[T-056]
    T057[T-057]
    T058[T-058]
    T059[T-059]
    T060[T-060]
    T061[T-061]
    T062[T-062]
    T063[T-063]
    T064[T-064]
    T065[T-065]
    T066[T-066]
    T067[T-067]
  end
  subgraph E6[E6 HITL и подарки]
    T076[T-076]
    T077[T-077]
    T078[T-078]
    T079[T-079]
    T080[T-080]
  end
  subgraph E7[E7 Рабочее место CX]
    T086[T-086]
    T087[T-087]
    T088[T-088]
    T089[T-089]
    T090[T-090]
    T091[T-091]
    T092[T-092]
    T093[T-093]
    T094[T-094]
  end
  subgraph E8[E8 «Под капотом»]
    T106[T-106]
    T107[T-107]
    T108[T-108]
    T109[T-109]
    T110[T-110]
    T201[T-201]
  end
  subgraph E9[E9 Лендинг, трекинг, Telegram-бот]
    T119[T-119]
    T120[T-120]
    T121[T-121]
    T122[T-122]
    T206[T-206]
  end
  subgraph E10[E10 Бенчмарки и экономика]
    T129[T-129]
    T130[T-130]
    T131[T-131]
    T132[T-132]
    T133[T-133]
    T202[T-202]
  end
  subgraph E11[E11 Сценарии и тесты]
    T141[T-141]
    T142[T-142]
    T143[T-143]
    T144[T-144]
    T145[T-145]
    T146[T-146]
  end
  subgraph E12[E12 Документация и защита]
    T151[T-151]
    T152[T-152]
    T153[T-153]
    T154[T-154]
    T204[T-204]
    T205[T-205]
  end
  subgraph E13[E13 Локализация]
    T156[T-156]
    T157[T-157]
    T203[T-203]
  end
  subgraph E14[E14 Поведение клиентов и калькулятор «Факт»]
    T161[T-161]
    T162[T-162]
    T163[T-163]
    T164[T-164]
    T165[T-165]
    T166[T-166]
    T167[T-167]
  end
  subgraph E15[E15 Внешние площадки и автономный возврат [BRD]]
    T171[T-171]
    T172[T-172]
    T173[T-173]
    T174[T-174]
    T175[T-175]
    T176[T-176]
    T177[T-177]
    T178[T-178]
    T179[T-179]
    T180[T-180]
  end
  subgraph E16[E16 Аудиомониторинг отделения и мисселлинг [BRD]]
    T181[T-181]
    T182[T-182]
    T183[T-183]
    T184[T-184]
    T185[T-185]
    T186[T-186]
    T187[T-187]
    T188[T-188]
    T189[T-189]
    T190[T-190]
    T191[T-191]
    T192[T-192]
    T193[T-193]
  end
  subgraph E17[E17 Режим подстраховки демо [BRD]]
    T194[T-194]
    T195[T-195]
    T196[T-196]
    T197[T-197]
    T198[T-198]
  end
  subgraph E18[E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ]]
    T207[T-207]
    T208[T-208]
    T209[T-209]
    T210[T-210]
    T211[T-211]
    T212[T-212]
    T213[T-213]
    T214[T-214]
    T215[T-215]
    T216[T-216]
    T217[T-217]
    T218[T-218]
    T219[T-219]
    T220[T-220]
    T221[T-221]
  end
  T001 --> T002
  T002 --> T003
  T005 --> T003
  T016 --> T003
  T001 --> T004
  T001 --> T005
  T001 --> T006
  T001 --> T007
  T004 --> T008
  T005 --> T008
  T004 --> T009
  T005 --> T009
  T046 --> T009
  T016 --> T009
  T007 --> T010
  T009 --> T010
  T013 --> T014
  T012 --> T015
  T013 --> T015
  T005 --> T016
  T011 --> T016
  T012 --> T016
  T016 --> T017
  T013 --> T017
  T017 --> T018
  T014 --> T018
  T012 --> T019
  T013 --> T019
  T014 --> T019
  T018 --> T020
  T019 --> T020
  T015 --> T020
  T040 --> T020
  T131 --> T020
  T161 --> T020
  T019 --> T021
  T016 --> T022
  T017 --> T022
  T018 --> T022
  T019 --> T022
  T020 --> T022
  T004 --> T031
  T005 --> T031
  T008 --> T031
  T031 --> T032
  T006 --> T032
  T032 --> T033
  T017 --> T033
  T032 --> T034
  T018 --> T034
  T032 --> T035
  T033 --> T035
  T032 --> T036
  T013 --> T036
  T046 --> T036
  T058 --> T036
  T031 --> T037
  T032 --> T037
  T014 --> T037
  T034 --> T038
  T036 --> T038
  T037 --> T038
  T040 --> T038
  T056 --> T038
  T161 --> T038
  T034 --> T039
  T056 --> T039
  T062 --> T039
  T005 --> T040
  T031 --> T040
  T032 --> T040
  T031 --> T041
  T040 --> T041
  T056 --> T041
  T058 --> T041
  T040 --> T042
  T132 --> T042
  T004 --> T046
  T006 --> T046
  T046 --> T047
  T046 --> T048
  T046 --> T049
  T014 --> T049
  T047 --> T050
  T048 --> T050
  T049 --> T050
  T050 --> T051
  T010 --> T051
  T046 --> T056
  T032 --> T056
  T005 --> T056
  T056 --> T057
  T005 --> T057
  T057 --> T058
  T014 --> T058
  T015 --> T058
  T057 --> T059
  T059 --> T060
  T046 --> T060
  T021 --> T060
  T060 --> T061
  T076 --> T061
  T061 --> T062
  T058 --> T062
  T062 --> T063
  T036 --> T063
  T078 --> T063
  T061 --> T064
  T039 --> T064
  T056 --> T065
  T008 --> T065
  T060 --> T066
  T061 --> T066
  T129 --> T066
  T062 --> T067
  T065 --> T067
  T049 --> T067
  T006 --> T076
  T014 --> T076
  T056 --> T077
  T061 --> T077
  T008 --> T077
  T058 --> T078
  T061 --> T078
  T015 --> T078
  T077 --> T078
  T077 --> T079
  T086 --> T079
  T078 --> T080
  T086 --> T080
  T040 --> T086
  T007 --> T086
  T008 --> T086
  T031 --> T086
  T086 --> T087
  T060 --> T087
  T086 --> T088
  T011 --> T088
  T086 --> T089
  T058 --> T089
  T037 --> T089
  T089 --> T090
  T091 --> T090
  T131 --> T090
  T063 --> T090
  T086 --> T091
  T161 --> T091
  T086 --> T092
  T063 --> T092
  T037 --> T092
  T086 --> T093
  T132 --> T093
  T086 --> T094
  T040 --> T094
  T042 --> T094
  T041 --> T094
  T065 --> T106
  T007 --> T106
  T008 --> T106
  T106 --> T107
  T056 --> T107
  T005 --> T108
  T008 --> T108
  T007 --> T108
  T067 --> T109
  T106 --> T109
  T163 --> T110
  T106 --> T110
  T007 --> T119
  T062 --> T119
  T119 --> T120
  T063 --> T120
  T062 --> T121
  T120 --> T121
  T121 --> T122
  T086 --> T122
  T060 --> T129
  T050 --> T129
  T021 --> T129
  T129 --> T130
  T007 --> T130
  T005 --> T131
  T015 --> T131
  T040 --> T132
  T131 --> T132
  T037 --> T132
  T161 --> T132
  T131 --> T133
  T007 --> T133
  T005 --> T141
  T049 --> T141
  T038 --> T142
  T141 --> T142
  T010 --> T143
  T086 --> T143
  T090 --> T143
  T106 --> T143
  T119 --> T143
  T033 --> T144
  T037 --> T144
  T087 --> T144
  T008 --> T144
  T001 --> T145
  T141 --> T145
  T143 --> T145
  T142 --> T146
  T040 --> T146
  T041 --> T146
  T042 --> T146
  T003 --> T151
  T038 --> T151
  T122 --> T151
  T001 --> T152
  T011 --> T152
  T001 --> T153
  T151 --> T154
  T093 --> T154
  T130 --> T154
  T010 --> T156
  T086 --> T156
  T090 --> T156
  T106 --> T156
  T119 --> T156
  T130 --> T156
  T133 --> T156
  T015 --> T157
  T062 --> T157
  T121 --> T157
  T012 --> T161
  T032 --> T161
  T031 --> T161
  T161 --> T162
  T033 --> T162
  T056 --> T162
  T161 --> T163
  T046 --> T163
  T049 --> T163
  T065 --> T163
  T161 --> T164
  T058 --> T164
  T131 --> T164
  T161 --> T165
  T131 --> T165
  T165 --> T166
  T164 --> T166
  T133 --> T166
  T161 --> T167
  T162 --> T167
  T163 --> T167
  T164 --> T167
  T005 --> T171
  T017 --> T171
  T040 --> T171
  T171 --> T172
  T056 --> T172
  T171 --> T173
  T057 --> T173
  T059 --> T173
  T172 --> T174
  T173 --> T174
  T060 --> T174
  T061 --> T174
  T062 --> T174
  T076 --> T174
  T171 --> T175
  T172 --> T175
  T058 --> T175
  T077 --> T175
  T171 --> T176
  T058 --> T176
  T032 --> T176
  T008 --> T176
  T176 --> T177
  T007 --> T177
  T008 --> T177
  T201 --> T177
  T016 --> T178
  T019 --> T178
  T021 --> T178
  T174 --> T179
  T175 --> T179
  T176 --> T179
  T038 --> T179
  T198 --> T179
  T040 --> T180
  T004 --> T181
  T005 --> T181
  T181 --> T182
  T007 --> T182
  T181 --> T183
  T180 --> T183
  T046 --> T183
  T005 --> T184
  T013 --> T184
  T183 --> T185
  T184 --> T185
  T047 --> T185
  T049 --> T185
  T185 --> T186
  T058 --> T186
  T077 --> T186
  T131 --> T186
  T182 --> T187
  T183 --> T187
  T186 --> T187
  T201 --> T187
  T186 --> T188
  T007 --> T188
  T186 --> T189
  T121 --> T189
  T184 --> T190
  T021 --> T190
  T185 --> T191
  T190 --> T191
  T129 --> T191
  T130 --> T191
  T186 --> T192
  T190 --> T192
  T038 --> T192
  T198 --> T192
  T181 --> T193
  T182 --> T193
  T046 --> T194
  T047 --> T194
  T049 --> T194
  T194 --> T195
  T086 --> T195
  T094 --> T195
  T040 --> T195
  T194 --> T196
  T174 --> T196
  T185 --> T196
  T003 --> T197
  T181 --> T197
  T194 --> T197
  T194 --> T198
  T174 --> T198
  T185 --> T198
  T066 --> T198
  T005 --> T199
  T006 --> T199
  T006 --> T200
  T004 --> T200
  T106 --> T201
  T008 --> T201
  T065 --> T201
  T131 --> T202
  T171 --> T202
  T186 --> T202
  T177 --> T203
  T187 --> T203
  T188 --> T203
  T195 --> T203
  T156 --> T203
  T151 --> T204
  T179 --> T204
  T192 --> T204
  T195 --> T204
  T153 --> T205
  T182 --> T206
  T067 --> T206
  T119 --> T206
  T221 --> T207
  T056 --> T207
  T058 --> T207
  T207 --> T208
  T207 --> T209
  T178 --> T209
  T059 --> T210
  T060 --> T210
  T129 --> T210
  T207 --> T210
  T210 --> T211
  T060 --> T212
  T210 --> T212
  T061 --> T213
  T062 --> T213
  T076 --> T213
  T207 --> T213
  T212 --> T213
  T213 --> T214
  T089 --> T214
  T106 --> T214
  T184 --> T215
  T185 --> T215
  T208 --> T216
  T215 --> T216
  T186 --> T216
  T216 --> T217
  T187 --> T217
  T188 --> T217
  T088 --> T218
  T093 --> T218
  T132 --> T218
  T207 --> T218
  T215 --> T218
  T190 --> T219
  T178 --> T219
  T216 --> T220
  T213 --> T220
  T214 --> T220
  T217 --> T220
  T218 --> T220
  T209 --> T220
  T198 --> T220
  T199 --> T221
  T200 --> T221
```

## Сводка

- Всего карточек: 150; по оценкам: S — 36, M — 89, L — 25.
- Критический путь (ядро): T-001 → T-005 → T-006 → T-046 → T-056 → T-057 → T-058 → T-061 → T-062 → T-063 → T-090 → T-142 → T-151.
- Критический путь v1.3 (BRD-1): T-005 → T-199 → T-171 → T-172 → T-174 → T-176 → T-177 → T-179; (BRD-2): T-181 → T-183 → T-185 → T-186 → T-187 → T-192; подстраховка T-194 → T-195 → T-198 нужна до первой репетиции.
- Демо-минимум (если времени не хватает): все карточки волн 1–3 (включая T-040 запуски и T-041 возобновление) плюс T-077, T-078, T-090, T-094, T-106, T-107, T-108, T-119, T-120, T-131, T-142, T-151. Бот (T-121/122), бенчмарк-UI (T-130), калькулятор «Факт» (T-166) и перф-тесты можно отложить без потери ключевого сценария.
- Демо-минимум v1.3 (контуры BRD): T-171–T-177, T-179, T-180, T-181–T-188, T-192, T-194–T-198, T-199–T-201, T-206. Отложить без потери показа можно: T-189 (Telegram-алерт), T-191 (бенчмарк детектора), T-193 (альтернативные STT), T-202–T-205, режим stereo в T-183.
- Карточки с пометкой [BRD] (E15–E17, T-199–T-206) добавлены в v1.3 по бизнес-требованиям демо-стенда; обоснование — docs/BRD-merge-analysis.md.
- Критический путь v1.4 (ДТЗ): T-199 → T-221 → T-207 → T-208 → T-210 → T-212 → T-213 → T-214; транскрипты: T-219 → T-215 → T-216 → T-217; карта: T-207 → T-218; замыкает T-220 (сценарии 10–11).
- Демо-минимум v1.4 (ДТЗ): T-207, T-208, T-210, T-212, T-213, T-214, T-215, T-216, T-217, T-218, T-219, T-220, T-221. Отложить без потери показа можно: T-209 (polling — сценарий 11 тогда вводится через REST) и T-211 (скрытый негатив — тогда сарказм ловится только порогом negativity).
- Карточки с пометкой [ДТЗ] (E18, T-207–T-221) добавлены в v1.4 по дополнительному ТЗ; обоснование — docs/TZ.md 0.6 и 20.6, docs/BRD-merge-analysis.md раздел «Дополнительное ТЗ».
