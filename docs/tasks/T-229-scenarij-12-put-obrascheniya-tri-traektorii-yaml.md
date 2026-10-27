# T-229 — Сценарий 12 «Путь обращения: три траектории»: YAML, кассеты, автотесты, блок E демо-скрипта

| Поле | Значение |
|---|---|
| Эпик | E22 Сквозная демонстрация «Путь обращения» [АРХ] |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | M (1–2 дня) |
| Волна | 9 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Автоматическая приёмка экрана «Путь обращения» на трёх траекториях и описание блока E демо-скрипта (ТЗ 18, сценарий 12).

## Разделы ТЗ (docs/TZ.md)
§18, §27.6, §19

## Контракты
- `data/scenarios/journey_three_trajectories.yaml`
- docs/DEMO-SCRIPT.md (блок E)

## Зависимости
- Зависит от: [T-227](T-227-put-obrascheniya-rezhimy-sledit-povtor-veduschij.md), [T-228](T-228-put-obrascheniya-dorozhka-glazami-klienta-emulya.md), [T-198](T-198-kassety-scenariev-8-9-i-avtotesty-na-nih-procedu.md)
- Блокирует: [T-260](T-260-dokumentaciya-v1-5-demo-skript-bloki-e-f-rukovod.md)

## Что сделать
1. `data/scenarios/journey_three_trajectories.yaml` (ID сценария 12): шаги и ожидания для траекторий (а) автономный возврат (сценарий 8), (б) HITL «Вклад» (сценарий 1), (в) уточнение и эскалация (сценарий 11); пункт в меню демонстратора.
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
cd frontend && npx playwright test e2e/journey-scenario.spec.ts
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
