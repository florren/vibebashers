# T-048 — конкретные границы предлагаемого LLM egress

Одобренный пользователем bounded запуск выполнен 2026-11-02; результат и ограничения зафиксированы ниже. Повторный запуск/замена моделей не разрешены этим отчётом.

Команда из `backend`: `.venv/bin/python -m app.llm.live_smoke --run`.

- Только HTTPS `openrouter.ai`, пути POST `/api/v1/chat/completions` и GET `/api/v1/key`; redirect, другие URL/порты/query/userinfo отвергаются transport guard.
- Только три фиксированных ID из T-048, максимум шесть HTTP запросов суммарно, в том числе budget preflight `/key`. Дополнительные запросы блокируются до сети; SDK retries=0.
- Каждый completion получает `max_tokens=128`, stream выключен; таймаут 15 с на запрос. Два прохода contract validation и однократный fallback json_schema→json_object ограничиваются общим сетевым бюджетом. При исчерпании бюджета часть моделей может остаться непроверенной — это явная ошибка, не mock-успех.
- Фиксированное сообщение: «В приложении Банка не открывается вклад. Прошу помочь.» и JSON schema классификации. Пользовательские тексты, реальные ПДн, файлы и содержимое БД не отправляются. `/key` получает только авторизацию; настройки бюджета читаются локально.
- Transport также запрещает отражённый Authorization credential в prompt исправляющей попытки; validation warnings не печатают raw invalid values.
- Ключ — только из существующего `OPENROUTER_API_KEY`. Вывод содержит ID моделей, ok/error kind/status, число запросов и известные токены; не содержит ключей, raw outputs и URL. Debug-логи SDK отключены внутри CLI.
- Политика budget из `T-048-budget-policy.md` сохраняется. Поскольку owl-alpha не имеет суффикса :free, требуется известный бюджет/usage. Приложение не утверждает, что все три ID сейчас бесплатны или доступны. Максимум output tokens не ограничивает размер input tokens; prompt фиксирован, schema — из репозитория.

Границы проверены unit tests на MockTransport. Успешный live smoke трёх моделей не подтверждён; DoD живого smoke не закрыт.


## Фактический результат одобренного запуска, 2026-11-02

Пользователь явно согласовал для PR159 «Политику и ограниченный live smoke». Выполнен ровно один существующий CLI на commit `92a235f` (runtime CLI/provider/budget byte-identical `d0fb457`), без изменений настроек и кода. Configuration source — canonical `.env` без вывода; read-only budget scalar settings.llm — из выделенной scratch `cx_openai_revision`. Данные клиентов/операций из БД не читались и не отправлялись.

Exit code 1; выполнено 5 HTTP-запросов из максимума 6; 3 фиксированных model IDs; max_output_tokens=128 на completion. `nvidia/nemotron-3-ultra-550b-a55b:free` — `bad_output`; `openrouter/owl-alpha` — `unavailable`, HTTP 404; `openai/gpt-oss-120b:free` — `unavailable`, HTTP 404. Schema не ослаблялась. Замен моделей, повторного запуска или обхода budget guard не было.

Actual tokens/actual USD при этих ошибках CLI не сообщил: расход неизвестен и не объявляется нулевым. Дополнительные HTTP-запросы ради учёта расходов не выполнялись. Очищенный машиночитаемый результат: `T-048-live-smoke-result.json`; stdout первоначального запуска — `/tmp/t048-approved-live-smoke.json`, stderr пуст. Ключи/headers/raw model outputs в tracked отчёт не включены.

Это диагностика внешнего code path, не успешная приёмка всех трёх моделей. Нужна актуализация доступного каталога T-047 и отдельное согласование нового bounded запуска; карточка T-048 остаётся in_progress.
