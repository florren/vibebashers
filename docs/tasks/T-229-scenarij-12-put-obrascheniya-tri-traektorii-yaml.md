# T-229 — Сценарий 12 «Путь обращения: три траектории»: YAML, кассеты, автотесты, блок E демо-скрипта

| Поле | Значение |
|---|---|
| Эпик | E22 Сквозная демонстрация «Путь обращения» [АРХ] |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | M (1–2 дня) |
| Волна | 9 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Автоматическая приёмка экрана «Путь обращения» на трёх траекториях и описание блока E демо-скрипта (ТЗ 18, сценарий 12).

## Разделы ТЗ (docs/TZ.md)
§18, §27.6, §19

## Контракты
- `data/scenarios/12_journey.yaml`
- docs/DEMO-SCRIPT.md (блок E)

## Зависимости
- Зависит от: [T-227](T-227-put-obrascheniya-rezhimy-sledit-povtor-veduschij.md), [T-228](T-228-put-obrascheniya-dorozhka-glazami-klienta-emulya.md), [T-198](T-198-kassety-scenariev-8-9-i-avtotesty-na-nih-procedu.md)
- Блокирует: [T-260](T-260-dokumentaciya-v1-5-demo-skript-bloki-e-f-rukovod.md)

## Что сделать
1. `data/scenarios/12_journey.yaml` (ID сценария 12): шаги и ожидания для траекторий (а) автономный возврат (сценарий 8), (б) HITL «Вклад» (сценарий 1), (в) уточнение и эскалация (сценарий 11); пункт в меню демонстратора.
2. Кассеты replay для трёх траекторий; автотесты backend: все применимые стадии, дорожка клиента совпадает с `notifications`/`external_replies`, бюджеты времени 27.6.
3. Playwright: «Следить», «Повтор», «Ведущий» на каждой траектории, скриншоты ключевых состояний.
4. Блок E демо-скрипта (+2 мин): порядок, тезисы, запасной вариант на кассетах (`docs/DEMO-SCRIPT.md`).

## Критерии приёмки
- [ ] `make scenario ID=journey_three_trajectories` зелёный на кассетах в CI и вручную на live.
- [ ] Блок E описан пошагово с таймингом.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=journey_three_trajectories
cd frontend && npx playwright test e2e/journey-modes.spec.ts
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._

## Ревизия: три native trajectories и собственная клиентская дорожка

Ветка codex/T-229-journey-acceptance. Реализованы read-only CLI/alias/меню12,
проверки трёх путей, исполнение сохранённой эскалации на тишине, корректный
адресат client lane по SIG/POST. API/DDL не меняются. Доказательства и точная
HITL граница: docs/reviews/T-229-journey-acceptance.md.

Runtime ab9b8da:1432unit/18skip,45unit/PG,96.52% новых строк;54actual browser
cases+6waiting-human frames,84table hashes stable,150GET p95≤40.135ms.
13 постоянных Playwright cases с явно mocked API,330frontend,lint/types/builds.
Полныйmake test1791backend/22skip+330frontend завершился, но post-fix готовился
во время прогона: он проверен отдельно и требует финального CI.

Карточка in_progress: нужны реальные replay/live recordings, итоговая demo
композиция, human review эскалации и green CI/merge. Cross-layer согласован;
нового разрешения на external LLM/Telegram не было и вызовов не выполнялось.
