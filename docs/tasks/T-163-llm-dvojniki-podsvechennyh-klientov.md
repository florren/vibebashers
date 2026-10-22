# T-163 — LLM-двойники «подсвеченных» клиентов

| Поле | Значение |
|---|---|
| Эпик | E14 Поведение клиентов и калькулятор «Факт» |
| Субагент | `SA-Behavior` (поведение клиентов) |
| Оценка | L (3–4 дня) |
| Волна | 3 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Живые тексты жалоб и реакций на лёгкой модели для сценариев, HITL, VIP и выборки; остальные — параметрически.

## Разделы ТЗ (docs/TZ.md)
§4.5, §12.5, §5.2

## Контракты
- `events/agent/client_twin_reaction.schema.json`
- `db/schema.sql: client_reactions, agent_runs (kind=client_twin)`

## Зависимости
- Зависит от: [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md), [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md), [T-065](T-065-trassirovka-zapuskov-i-striming-tokenov.md)
- Блокирует: [T-110](T-110-dialog-agent-dvojnik-i-sostoyanie-klienta.md), [T-167](T-167-statisticheskie-testy-modeli-povedeniya.md)

## Что сделать
1. prompts/v1/twin.md: роль клиента с психотипом/сегментом/продуктом, что он видел (уведомления, ответы), фактическое состояние проблемы с его точки зрения; запрет на знание внутренних данных; структурированный ответ по схеме.
2. Выбор подсвеченных: сценарии, HITL, vip/ultra_vip, случайная выборка ≤ settings.twins.daily_limit; профиль роли twin (Lightning по умолчанию, mock в офлайне).
3. Реакция → client_reactions, при asks_again/escalates → новый сигнал (signal.repeat) с текстом двойника; satisfaction влияет на care_score; запуски kind=client_twin в трассировке с отдельным учётом токенов.

## Критерии приёмки
- [ ] В сценарии 1 двойник VIP отвечает текстом на уведомления; тексты валидны по схеме и правдоподобны (ревью 10).
- [ ] Расход токенов двойников ≤ 15 % от общего на демо.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_twins.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
