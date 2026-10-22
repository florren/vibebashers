# T-185 — LLM-детектор мисселлинга (Lightning), подтверждение/снятие отметки, failover

| Поле | Значение |
|---|---|
| Эпик | E16 Аудиомониторинг отделения и мисселлинг [BRD] |
| Субагент | `SA-Compliance` (аудиосессии, детектор мисселлинга, алерты [BRD]) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Второй этап гибрида: быстрая модель подтверждает или снимает предварительную отметку в пределах 2 с с цитатой и уверенностью (ТЗ 22.4, 16.4).

## Разделы ТЗ (docs/TZ.md)
§22.4, §16.4, §5.2

## Контракты
- `events/compliance/misselling_verdict.schema.json`
- `db/schema.sql: compliance_triggers, agent_runs.kind = compliance_detector`

## Зависимости
- Зависит от: [T-183](T-183-audiosessii-repliki-i-tri-rezhima-razdeleniya-sp.md), [T-184](T-184-taksonomiya-missellinga-i-rule-detektor-predvari.md), [T-047](T-047-gigachat-provajder-s-pulom-klyuchej-i-uchetom-to.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md)
- Блокирует: [T-186](T-186-schetchik-narushenij-mashina-sostoyanij-sessii-a.md), [T-191](T-191-benchmark-detektora-missellinga-i-stt-ranner-met.md), [T-196](T-196-avtomaticheskij-failover-po-tajmautu-i-oshibkam.md), [T-198](T-198-kassety-scenariev-8-9-i-avtotesty-na-nih-procedu.md), [T-215](T-215-taksonomiya-krasnyh-fraz-semejstvo-conduct-ruden.md)

## Что сделать
1. app/compliance/llm_detector.py: промпт prompts/v1/misselling_detect.md (таксономия, продукт сделки, последние 6 реплик, требование дословной цитаты-подстроки), structured output misselling_verdict; профиль по умолчанию GigaChat-3-Lightning, настраиваемый.
2. Конвейер: финал реплики сотрудника → rules (preliminary) → LLM ≤ 2 с → confirmed (≥ 0,6) или dismissed; при недоступности LLM > 2 с — отметка правила ≥ 0,85 засчитывается с пометкой «по правилу» (detected_by=rules), иначе ждёт; не более одного триггера на реплику.
3. Трассировка каждого вызова в agent_runs(kind=compliance_detector)/agent_steps(node=detect_misselling) с токенами и латентностью; mock-детектор = rules для офлайна и бенчмарка.
4. События compliance.trigger и топик WebSocket compliance; кассеты replay для сценария 9.

## Критерии приёмки
- [ ] На наборе misselling_v1 F1 ≥ 0,8 для выбранной модели, «чистые» фразы не подтверждаются.
- [ ] Латентность финал → статус ≤ 2 с (p50) на Lightning; failover по таймауту покрыт тестом.
- [ ] Цитата всегда является подстрокой реплики (валидация).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_misselling_llm.py
make bench DATASET=misselling_v1
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
