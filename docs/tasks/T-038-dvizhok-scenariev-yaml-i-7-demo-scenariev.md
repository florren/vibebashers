# T-038 — Движок сценариев YAML и 7 демо-сценариев

| Поле | Значение |
|---|---|
| Эпик | E3 Симулятор банка, команды, SLA |
| Субагент | `SA-Scenarios` (сценарии) |
| Оценка | L (3–4 дня) |
| Волна | 4 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Воспроизводимые демонстрации из ТЗ 18 с проверяемыми ожиданиями.

## Разделы ТЗ (docs/TZ.md)
§18, §4.6, §17 E11

## Контракты
- `api/openapi.yaml: scenarios/*, sim/runs`
- `db/schema.sql: scenarios, sim_runs`

## Зависимости
- Зависит от: [T-034](T-034-generator-sboev-i-vosstanovlenij.md), [T-036](T-036-emulyator-komand-i-cifrovoj-sled-incidenta.md), [T-037](T-037-sla-dvizhok.md), [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md), [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md), [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md)
- Блокирует: [T-142](T-142-avtotesty-7-demo-scenariev.md), [T-151](T-151-readme-i-demo-skript.md), [T-179](T-179-scenarij-8-komissiya-za-qr-oplatu-i-publichnyj-o.md), [T-192](T-192-scenarij-9-misselling-v-otdelenii-yaml-avtotest.md)

## Что сделать
1. Формат YAML: шаги с относительным сим-временем (inject_fault, inject_signal, wait, expect), параметры клиента (сегмент, психотип, регион), ожидания (инциденты, команды, уведомления, статусы, подарки, состояния клиента, экономика).
2. app/sim/scenarios/runner.py: каждый запуск сценария — отдельный sim_run (kind=scenario) через сервис запусков T-040 с режимом сброса counters|baseline (сценарии 1, 4, 7 с именованными клиентами требуют baseline, иначе 409); результат в scenarios.last_result и sim_runs.summary.
3. 7 сценариев: deposit_promo_rate, double_fee, jury_input, potential_client (бот/лендинг), deferred_fraud, mass_notif, silent_churn_regression — тексты и ожидания из ТЗ 18.
4. API list/run; кнопка запуска в UI (T-086).

## Критерии приёмки
- [ ] Каждый сценарий проходит на mock-LLM автотестом и на GigaChat-3-Ultra вручную (лог прилагается к PR).
- [ ] Ключевой сценарий 1 укладывается в 3 мин при пресете demo_5min.
- [ ] Повторный запуск сценария в режиме baseline с тем же сидом на mock даёт идентичные события и summary; в режиме counters показатели нового запуска не содержат данных предыдущего (ТЗ 19 п. 16).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=deposit_promo_rate
pytest backend/tests/scenarios
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
