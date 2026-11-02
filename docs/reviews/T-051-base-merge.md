# T-051: проверенная база SDK + durable LangGraph

Dependency-only ordinary merge `34711ec` в `6d7e5e`; реализация T-051 и миграция0013 ещё не добавлены.

Сохранены SDK provider close/budget callbacks, startup recovery перед actors, strict durable resume, parent HITL guards. `wake_due_followups` сохраняет одновременно фильтры `signal_id` и `run_id`, причины `awaiting_client`, checkpoint и legacy exclusions. OpenAPI объединён с версией1.5.15; frontend i18n/WS содержит обе стороны изменений.

Отдельный `uv sync` в этом worktree сохраняет версии T-041 lock и добавляет OpenAI SDK/jiter. License inventory пересобран из установленного окружения и проверенных platform-only wheel:113 Python+437 npm=550; canonical venv не изменялся.

Проверки: full unit1038passed/18skipped (31.46s); frontend171passed/30files; `make lint` прошёл (ruff/format356,mypy252,frontend lint/tsc,OpenAPI drift191/191); contracts44schemas/161paths; licenses550. В frontend остаётся прежнее предупреждение DemoMenu FastRefresh.

На отдельной synthetic БД `cx_profile_hotapply_revision` прошли22 PG tests (87.18s): durable graph, process restart, run profiles, lifecycle, public tracking/claim. Первый subset дал21pass/1fail из-за запуска только с DATABASE_URL_TEST: Settings закешировал другой DATABASE_URL до monkeypatch API fixture. Повтор с обоими URL, заданными scratch с начала процесса, зелёный; runtime/assertions для этого не менялись. В listener unit fake добавлены AsyncMock.close и проверка вызова: T-041 теперь закрывает connection в finally, исходная проверка submit сохранена.

Это проверка базы, не заявление о готовности T-051. Full make test и новые P1 проверки выполняются после реализации. Live LLM не вызывались; push/PR/merge в main не выполнялись.
