# T-066 — Версионирование промптов и gate на lite-бенчмарке

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Prompts` (промпты и классификатор) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 4 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Любое изменение промпта измеримо и обратимо.

## Разделы ТЗ (docs/TZ.md)
§9.4, §14.3

## Контракты
- `db/schema.sql: agent_runs.prompt_version, bench_runs`

## Зависимости
- Зависит от: [T-060](T-060-uzel-classify-i-prompty-v1.md), [T-061](T-061-uzel-decide-sla-marshrutizaciya-prioritet-politi.md), [T-129](T-129-benchmark-ranner-i-metriki.md)
- Блокирует: [T-198](T-198-kassety-scenariev-8-9-i-avtotesty-na-nih-procedu.md)

## Что сделать
1. prompts/vN/ с фронтматтером; загрузчик с выбором версии из настроек; prompt_version в запусках.
2. CI-джоб (ручной) `make bench DATASET=lite_v1 PROFILE=mock` при изменении prompts/ — без расхода токенов; инструкция для ручного прогона на Lightning.
3. docs/prompts.md: что меняли и зачем, метрики до/после.

## Критерии приёмки
- [ ] Смена версии через настройки без рестарта.
- [ ] PR с изменением промпта содержит таблицу метрик.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make bench DATASET=lite_v1 PROFILE=mock
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
