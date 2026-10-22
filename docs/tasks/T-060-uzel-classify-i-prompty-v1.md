# T-060 — Узел classify и промпты v1

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Prompts` (промпты и классификатор) |
| Оценка | L (3–4 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Классификация с объяснением по схеме classification; few-shot из решений людей.

## Разделы ТЗ (docs/TZ.md)
§7, §9.4, §12.5, §14.2

## Контракты
- `events/agent/classification.schema.json`

## Зависимости
- Зависит от: [T-059](T-059-uzly-ingest-normalize-identify-client-gather-con.md), [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md), [T-021](T-021-zolotoj-nabor-benchmarka-golden-v1-i-lite-v1.md)
- Блокирует: [T-061](T-061-uzel-decide-sla-marshrutizaciya-prioritet-politi.md), [T-066](T-066-versionirovanie-promptov-i-gate-na-lite-benchmar.md), [T-087](T-087-lenta-signalov.md), [T-129](T-129-benchmark-ranner-i-metriki.md), [T-174](T-174-bystryj-put-agenta-uslovnoe-rebro-act-instant-st.md), [T-210](T-210-trehklassnaya-tonalnost-sentiment-prompt-soglaso.md), [T-212](T-212-problem-summary-problem-severity-suggested-team.md)

## Что сделать
1. prompts/v1/classify.md: роль, таксономия ТЗ 7 с определениями и граничными случаями, правила тона/флагов, требования к rationale_ru, формат вывода; переменные контекста.
2. Few-shot: до 3 примеров из human_decisions (use_as_fewshot) по близости типа/канала.
3. Пост-проверки: согласованность product↔system, churn_risk vs флаг churn_intent, confidence; при конфликте — human_reason=classifier_conflict.
4. Прогон на lite_v1 с Ultra, Lightning, mock — таблица в PR.

## Критерии приёмки
- [ ] Ultra на golden: accuracy_type ≥ 0.85, recall по критичным ≥ 0.9, json_valid_rate ≥ 0.98.
- [ ] rationale_ru осмысленный и не повторяет текст сигнала (ревью 20 случайных).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make bench DATASET=lite_v1
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
