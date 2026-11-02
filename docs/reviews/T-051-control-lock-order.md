# T-051 composition: порядок блокировок pause/stop

При полном прогоне11f152 исходный OS-process тест T-041 превысил45s после записи graceful report. Same AgentRun, tokens и resumed_count уже были восстановлены. Повтор без изменения timeout воспроизвёл отказ. Временная synthetic-only диагностика без locals показала manual worker в `demo.settings.save` на UPDATE sim_runs; diagnostic code полностью удалён, fixture durable_process byte-identical исходной.

Причина: `Simulator.control(pause/stop)` получал row lock sim_runs до Python `sim._lock`, а manual_cycle удерживал Python lock и ожидал ту же строку. Две операции образовывали цикл. Это существующая ошибка concurrency, проявившаяся при композиции; не изменение финансовой/HITL политики.

Теперь сначала останавливается sim loop, затем один Python lock охватывает configuration/status/demo metadata/persist/commit. После commit и освобождения lock публикуется control event. Ошибка, включая CancelledError, выполняет rollback и возвращает прежний in-memory run_status; clock физически остановлен, ошибка не скрывается. Прежние условия смены статуса, finished_sim для stop, time/RNG и demo enable flags сохранены. Дубли старых pause/stop branches удалены.

Targeted evidence: оба pause/stop two-connection/event case проходят; тест проверяет ownership до фактического row write, сохранение независимого worker update, RNG/time/status/finished_sim. Ещё4 case доказывают rollback при RuntimeError/CancelledError. Исходный kill/restart/graceful subprocess проходит с прежними45s и всеми assertions. В общем target10case PASS; отдельный поздний отказ нового legacy fixture был отсутствующим обязательным label, не control regression.

В отдельной first-install fixture сбрасываются оба тестовых namespace langgraph/public перед Alembic, как уже делает общий conftest. Иначе прежние checkpoints переживали DROP public и FK ссылался на отсутствующую строку нового sim_runs. Исходные installation assertions сохранены; targeted case проходит.
