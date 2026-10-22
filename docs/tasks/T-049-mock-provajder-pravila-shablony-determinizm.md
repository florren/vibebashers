# T-049 — Mock-провайдер (правила + шаблоны, детерминизм)

| Поле | Значение |
|---|---|
| Эпик | E4 LLM-слой |
| Субагент | `SA-LLM` (LLM-слой) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Офлайн-режим, предыстория без расхода токенов и «противник» для панели «ИИ против правил».

## Разделы ТЗ (docs/TZ.md)
§5.2, §12.5, §16.2

## Контракты
- `events/agent/classification.schema.json`
- `events/agent/decision.schema.json`
- `events/agent/client_twin_reaction.schema.json`

## Зависимости
- Зависит от: [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md), [T-014](T-014-kody-oshibok-tipy-signalov-pravila-marshrutizaci.md)
- Блокирует: [T-050](T-050-rate-limiter-byudzhety-fallback-i-maskirovanie-s.md), [T-067](T-067-zhyuri-rezhim-ruchnoj-vvod-signala-i-sravnenie-s.md), [T-141](T-141-testovaya-infrastruktura-backend.md), [T-163](T-163-llm-dvojniki-podsvechennyh-klientov.md), [T-185](T-185-llm-detektor-missellinga-lightning-podtverzhdeni.md), [T-194](T-194-provajder-replay-kassety-zapisannyh-otvetov-mode.md)

## Что сделать
1. Классификация по ключевым словам/регуляркам и error_code в контексте; намеренно без понимания сарказма/многотемности; confidence по числу совпадений.
2. Решение по правилам маршрутизации и матрице SLA; тексты клиенту из шаблонов; rationale_ru шаблонный с перечислением сработавших правил (чтобы было видно отличие от LLM).
3. Двойник-mock: реакции по параметрам психотипа и care_score (без текста или с шаблонным текстом).
4. Полный детерминизм при одинаковом входе.

## Критерии приёмки
- [ ] Mock даёт accuracy_type 0.6–0.8 на golden (не слишком плох и не слишком хорош).
- [ ] Все выходы валидны по схемам.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_mock_provider.py
```

## Отчёт субагента
Коммит B02. `app/llm/mock.py`: `analyze(text)` — словарные эвристики (негатив/позитив, сарказм, отток, регулятор, публичность, возврат, вопрос, мошенничество, тариф/тех/сервис, продукт/система, сумма ₽) → negativity 0–100, sentiment, tone, signal_type, intents, flags, criticality, команда. `fill(schema)` — детерминированное заполнение любой разыменованной схемы (enum/anyOf/allOf с if-then/массивы/строки с min/maxLength/числа с границами), поля с известными именами (summary_ru, rationale_ru, public_reply_ru, needs_human, churn_risk, hidden_negativity.*.present …) берутся из эвристик; результат валидируется jsonschema перед возвратом. Seed = sha256 текста. Тесты: все 10 контрактов `agent/*` × 6 текстов валидны, детерминизм, сарказм/отток/благодарность распознаются. Отклонение: accuracy_type 0.6–0.8 на golden не измерялась — golden-набор появится в B21 (bench/*.jsonl), тогда добавить замер в T-129.
