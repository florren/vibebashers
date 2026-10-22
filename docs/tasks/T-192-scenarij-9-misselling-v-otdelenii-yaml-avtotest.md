# T-192 — Сценарий 9 «Мисселлинг в отделении»: YAML, автотест с файла и транскрипта

| Поле | Значение |
|---|---|
| Эпик | E16 Аудиомониторинг отделения и мисселлинг [BRD] |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Автопроверяемый сценарий BRD-2: три фразы → ALERT ≤ 3 с, алерт руководителю, инцидент misselling, HITL (ТЗ 18 п. 9, 19 п. 20–22).

## Разделы ТЗ (docs/TZ.md)
§18, §19

## Контракты
- `backend/tests/scenarios/fixtures/scenario_09.yaml`
- docs/TZ.md 18 сценарий 9

## Зависимости
- Зависит от: [T-186](T-186-schetchik-narushenij-mashina-sostoyanij-sessii-a.md), [T-190](T-190-dialogi-otdeleniya-nabor-misselling-v1-predzapis.md), [T-038](T-038-dvizhok-scenariev-yaml-i-7-demo-scenariev.md), [T-198](T-198-kassety-scenariev-8-9-i-avtotesty-na-nih-procedu.md)
- Блокирует: [T-204](T-204-demo-skript-7-8-i-3-5-minut-readme-razdelov-zhiv.md)

## Что сделать
1. YAML: ВСП № 0042 Самара, стол 3, Петров П. П., клиент social с вкладом 400 000 ₽, сделка ИСЖ; реплики с ролями; ожидания: триггеры tie_in → substitution → concealment, статусы confirmed, alerted, compliance.alert, инцидент misselling в team_compliance, HITL go → in_progress.
2. Прогон из транскрипта (детерминирован, CI) и из WAV через Vosk (маркер slow): задержки по шагам; кассета replay для LLM-детектора.
3. Негативный вариант 9b: диалог без нарушений — счётчик 0/3, алерта нет.

## Критерии приёмки
- [ ] CI-тест на транскрипте и кассете ≤ 60 с; slow-тест на WAV зелёный на 4 ядрах.
- [ ] Задержка третья фраза → счётчик ≤ 3 с в отчёте.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=branch_misselling
pytest backend/tests/scenarios/test_scenario_09_misselling.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
