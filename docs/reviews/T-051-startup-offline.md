# T-051: startup offline boundary

Root review7f96646 подтвердил Fake-only counterexample: APP_ENV=dev/LLM_PROVIDER=mock, explicit offline chain с физически сохранённым OpenAICompatProvider всё равно выполнял GET /api/v1/models. Empty Fake catalog не создавал plan/DB writes; реальных HTTP/DB/credential probes не было. Role refresh делал mock profiles, но catalog sync ориентировался только на наличие физического provider. Ошибка startup path, не permission diagnostic API.

Sourcef05b3b0 добавляет одинаковую explicit offline проверку перед Giga warmup/OpenRouter startup sync и внутри прямого _sync_openrouter_models. Settings.llm_provider mock/replay либо chain.offline_mode mock/replay запрещают automatic metadata egress. Локальный refresh_roles сохранён: replay может читать выбранные profiles из PostgreSQL. Полный startup0DB не заявляется; DB bomb проверяет mock case и отсутствие неожиданных deactivation writes. Setup test-llm и selected benchmark diagnostic intent не изменены.

45 targeted tests прошли3.55s: actual mock role refresh, четырёхсторонний Settings/chain guard, Fake catalog с HTTP recorder и DB connect bomb, Giga prepare bomb. Existing online case теперь вызывает actual _prepare_runtime_profiles и сохраняет исходные missing-model/deactivation/commit assertions. Ни HTTP fallback, ни новые retries/models/default budgets не добавлены.

Scoped stdlib trace на точномf05b3b0:16/17 changed executable statements=94.12%; missing line214 — прежний Giga prepare invocation в online branch, перемещённый при guard restructuring. Схема/контракты/DI diagnostics не менялись. Full make lint green:220frontend, Ruff398, mypy268, drift192/192. Machine coverage в T-051-startup-offline-coverage.json.

Предыдущий frozen43 aggregate и90.55% whole-packet coverage остаются историческими source-qualified доказательствами. Новый startup source ими полностью не покрывается; настоящий exact final-head GitHub CI обязателен. Нет новых live LLM/TG/email calls, env/key-registry reads, production изменений или canonical venv mutations.

После публикации4981f45 все четыре backend CI shards, db, lint, frontend,
images и e2e прошли. Aggregate tests был red из-за единственного contracts gate:
gen_tasks удалял пустую строку после heading отчёта T051. Исправление6105556 —
только canonical generator output, assertions/gates не менялись.
После ordinary merge mainf51c8ed (circadian T252) checkpoint4bb5469:
make lint exit0,324frontend passed, Ruff398/mypy268/drift192.
Backend runtime остаётся тем же, новые frontend тесты пришли из проверенного main.
Полный CI новой композиции обязателен; предыдущие checkpoints не подменяют его.
