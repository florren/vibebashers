# T-161: admission и переход к следующему дню

Пакет остаётся выключенным (`enabled: false`): это промежуточный source checkpoint, а не завершённая runtime/CI приёмка.

Проверка совместимости выполняется до эффектов graph/control/recovery. Непустой legacy `free`/`scenario` без behavior marker отклоняется с требованием нового run; учитываются не только операции/сигналы, но и события, уведомления, инциденты, реакции и agent_runs. Неизвестные старые таймеры не реконструируются. Production factories в main и CLI проверки явно получают `configured_policy()`; `Simulator(..., behavior_policy=None)` также загружает конфигурацию и не отключает модель.

## Отдельная семантическая граница для финального review

При включённой модели `reset_day` проходит обычными Sim ticks до 09:00 следующего **календарного** дня. Это изменение прежнего поведения (переставить часы и очистить pending), которое нельзя считать одобренным одним лишь выбором variant A для `churn_risk`. Потребители: HTTP sim control, кнопка UI и CLI/scenario consumers того же Simulator. Выходные не пропускаются; существующий рабочий календарь SLA/терпения остаётся пн–пт 09:00–18:00. Значения вероятностей и policy не меняются.

## Проверено на собственной PostgreSQL 16 scratch базе

- 6 регрессий: event-only legacy run для start/resume/step/jump_to/reset_day и graph до AR/role/provider effects — **6 passed, 34.84 s**.
- Пятница 23:55 → суббота 09:00: реальный pending signal доставлен в исходный due SimTime; day_no увеличился ровно на один; рабочий patience deadline остался неизменным и pending; persisted clock/RNG совпадают с Simulator — **1 passed, 7.88 s**.

Логи: `/tmp/t161-legacy-admission-final.log`, `/tmp/t161-reset-day-final.log`. Они относятся к этому checkpoint; полного финального regression/coverage/CI ещё нет. `verify_demo20_live.py` не запускался, выполнена только статическая проверка.
