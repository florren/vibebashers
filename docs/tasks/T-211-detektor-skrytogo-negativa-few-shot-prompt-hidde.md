# T-211 — Детектор скрытого негатива few-shot: промпт hidden_negativity.md, объект hidden_negativity, флаги, набор hidden_negativity_v1

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-Prompts` (промпты и классификатор) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Сарказм, пассивная агрессия и угроза ухода распознаются few-shot промптом с цитатой-доказательством и влияют на negativity и эскалацию (ДТЗ FR-2.2, ТЗ 7, критерий 28).

## Разделы ТЗ (docs/TZ.md)
§7, §9.3, §14.3, §19

## Контракты
- `events/agent/normalization.schema.json: hidden_negativity`
- `events/common.schema.json: flag (passive_aggression)`

## Зависимости
- Зависит от: [T-210](T-210-trehklassnaya-tonalnost-sentiment-prompt-soglaso.md)
- Блокирует: —

## Что сделать
1. prompts/v1/hidden_negativity.md: ≥ 12 размеченных примеров на класс + контрпримеры (искренняя благодарность, нейтральный вопрос о закрытии счёта по переезду); вызывается в узле normalize одним запросом с нормализацией (без второго вызова LLM).
2. Постобработка: флаги sarcasm / passive_aggression / churn_intent; сарказм при формально позитивном тексте → negativity ≥ 60 и sentiment=negative; evidence_ru обязан быть подстрокой текста (проверка, иначе null и confidence×0,7).
3. Набор data/bench/hidden_negativity_v1.jsonl (120); метрики precision/recall по классам в раннере бенчмарка.
4. Мок-провайдер: детерминированные правила по маркерам («ну конечно», «как всегда», «пора менять банк») для офлайн-тестов.

## Критерии приёмки
- [ ] recall ≥ 0,75 при precision ≥ 0,7 по всем трём классам на основном провайдере.
- [ ] Сценарий 11: sarcasm.present=true с цитатой «очень приятно».
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make bench SET=hidden_negativity_v1
pytest backend/tests/unit/test_hidden_negativity.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
