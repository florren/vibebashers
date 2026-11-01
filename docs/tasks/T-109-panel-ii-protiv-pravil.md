# T-109 — Панель «ИИ против правил»

| Поле | Значение |
|---|---|
| Эпик | E8 «Под капотом» |
| Субагент | `SA-UI-Engine` («Под капотом») |
| Оценка | S (≤ 0,5 дня) |
| Волна | 5 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
Экран 4д: сравнение классификации LLM и mock по одному тексту с подсветкой различий и объяснением.

## Разделы ТЗ (docs/TZ.md)
§12.5 приём 4

## Контракты
- `api/openapi.yaml: agent/compare`

## Зависимости
- Зависит от: [T-067](T-067-zhyuri-rezhim-ruchnoj-vvod-signala-i-sravnenie-s.md), [T-106](T-106-zhivaya-trassirovka-agenta.md)
- Блокирует: —

## Что сделать
1. Форма текста/канала/клиента, выбор профиля; две колонки результатов, diff полей, rationale обоих; быстрые примеры из «сложных» шаблонов (сарказм, многотемность).

## Критерии приёмки
- [ ] На 5 встроенных примерах LLM и mock расходятся минимум в 3 (демонстрация ценности).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/engine_compare.spec.ts
```

## Отчёт субагента
Ветка `codex/T-109-agent-compare` от main `5075355`; отдельные producer-коммиты `4d84be0` и `8f65c4d` сохраняют actual provider:model в compare trace; пустой usage.model обозначается unknown и не подменяется requested profile. Контракты, миграции, generated types и глобальные настройки LLM не менялись. Cross-layer согласован координатором: узкий backend producer, его PG tests, docs/TZ.md и screenshots, frontend/e2e.

В Engine добавлена вкладка `?tab=compare` с формой текста (3..5000), канала, optional positive safe client ID и активного профиля (включая bench_only — ручное сравнение разрешено). Default «Текущий настроенный» не отправляет llm_profile_id. Submit — одно явное действие без автоматического retry; pending блокирует повтор/изменение входа. Изменение входа убирает старый результат, WS/query invalidation не повторяет POST. Ошибки API/профилей/trace показаны явно; пустой HTTP200 не изображается как успешная классификация.

Две колонки показывают исходные rationale/summary, фактический step.model и источник mock/replay/live из trace, fallback и ссылки на два сохранённых диагностических прогона. Requested profile не используется как доказательство фактической модели. Legacy записи без префикса помечаются «Источник неизвестен». Все classification fields из DTO сравниваются структурно, с подсветкой и текстом «Различается»; порядок ключей объекта не считается отличием. Счётчик показывает именно API diff (его подмножество полей), таблица — все полученные поля; это явно объяснено. Уверенность0..1 и churn_risk0..100 форматируются по своим шкалам. Отсутствующие значения — «—». Существующие tEnum и UI tokens сохранены.

Пять ru/en синтетических примеров (сарказм, ирония, опечатки, косвенное намерение, несколько тем) заполняют только текст; ответы в production не заготовлены. Fixtures с условными различиями используются только unit/browser tests и прямо помечены test-only. Совпадение API diff выводится честно, не считается доказательством ценности LLM. Existing Compare DTO не содержит нормализацию negativity, результаты business rules и фактический router_action; отсутствующие колонки не фабрикуются, контракт не расширялся.

Точное устаревшее предложение ТЗ 12.5 приведено к явно согласованным при T-067/PR#152 границам:3..5000/20RPM/429. Пределы API не изменены. UI и DTO строки ru/en; rationale/summary сохраняют исходный язык ответа, о чём есть подпись.

Проверено до финального отчёта: 10 новых UI unit tests; полный make lint — 166 frontend tests, Ruff: 336, mypy: 246, drift191/191; обе production сборки. Production Playwright: 6 passed/0retries: ru/en × light/dark, mobile390 и global overflow≤2px,5 примеров без POST до Submit, active bench_only, selected model vs actual provenance, equal/unknown/fallback,граница 5000/invalid client/pending/429. 12 PNG в docs/screenshots/compare/compare-{form,results,mobile}-{ru,en}-{light,dark}.png. Fixtures полностью page-local API/WS, shared server/DB эта группа не меняет. Первоначальный producer PG suite: 7 passed/24.74 s — genuine MockProvider/ReplayProvider с test-only cassette transport, fallback с failing transport, POST→GETtrace, фактические model/status и сохранность signals.

Отдельный реальный offline proof: production UI без API fixtures на собственной cx_compare_ui_revision отправил все 5 встроенных входов с выбранным active Mock profile и client ID. Получены 10 реальных kind=compare traces с model=mock:mock-rules-v1 и diff_counts=[0,0,0,0,0]. UI отобразил совпадения, ссылки соответствуют сохранённым IDs. Hashes/counts всех 20 доменных таблиц до/после совпали; реальные LLM/email/Telegram и внешние browser origins отсутствовали. Proof /tmp/vibebashers-t109-real-proof.json, actual screenshot /tmp/vibebashers-t109-real-ui.png. Реальный API остановлен перед полным pytest.

Полный `make test` завершился exit0: 1209 backend passed / 22 skipped (unit 909, integration 227, scenarios 42, compliance 31) и 166 frontend passed; contracts: 44 schemas/161 paths. После полного прогона добавлен только edge guard usage.model пустой→unknown: final PG suite: 8 passed/36.62 s с genuine Mock/Replay/fallback/missing-model и baseline mock status=ok. Новая executable backend-строка покрыта 1/1 (100%) стандартным sys/threading tracer; полной module coverage не заявлено, pytest-cov в окружении отсутствует и зависимости не устанавливались. Final make lint повторно green: 166 frontend, Ruff: 336, mypy: 246, drift191. Новый полный прогон после единичного guard не повторялся; общий финальный compose/CI выполняет координатор. i18n: 1656, TS regenerate без diff, gen_tasks: 205 first/repeat idempotent. Условные fixture markers не входят в main/personal production bundles. Созданы 12 PNG; вручную просмотрены формы ru/light и en/dark, результаты ru/dark и mobile en/light. Собственные серверы остановлены. Статус in_progress: критерий ≥3/5 расхождений и live GigaChat из общего DoD не доказаны в mock-only режиме. Полная приёмка требует отдельно разрешённого bounded live либо честного существующего replay proof; условные UI fixtures таким доказательством не являются. PR/push/merge выполняет координатор.

Followup после normal merge main `8bb7394` (HEAD `2f83d15`): Trace projection теперь распознаёт и новый `replay:`, и legacy `replay/`, включая `replay:unknown`. Проверено через настоящий POST compare → GET agent-run trace → GET business trace: badge соответствует actual Mock/Replay/fallback/missing-model, не запрошенному профилю. Сохранены privacy/legacy unit assertions. Адресный прогон:48 passed за20.63s, Ruff зелёный; контракт и данные не менялись.
