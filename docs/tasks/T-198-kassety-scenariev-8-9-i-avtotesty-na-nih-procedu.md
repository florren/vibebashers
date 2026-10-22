# T-198 — Кассеты сценариев 8–9 и автотесты на них; процедура перезаписи при смене промптов

| Поле | Значение |
|---|---|
| Эпик | E17 Режим подстраховки демо [BRD] |
| Субагент | `SA-LLM` (LLM-слой) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 4 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Детерминированные кассеты для ключевых демо-сценариев и CI; регламент обновления (ТЗ 5.4, 15 SA-Cassettes).

## Разделы ТЗ (docs/TZ.md)
§5.4, §15, §18

## Контракты
- `db/schema.sql: llm_cassettes, demo_assets`
- docs/tasks: T-179, T-192

## Зависимости
- Зависит от: [T-194](T-194-provajder-replay-kassety-zapisannyh-otvetov-mode.md), [T-174](T-174-bystryj-put-agenta-uslovnoe-rebro-act-instant-st.md), [T-185](T-185-llm-detektor-missellinga-lightning-podtverzhdeni.md), [T-066](T-066-versionirovanie-promptov-i-gate-na-lite-benchmar.md)
- Блокирует: [T-179](T-179-scenarij-8-komissiya-za-qr-oplatu-i-publichnyj-o.md), [T-192](T-192-scenarij-9-misselling-v-otdelenii-yaml-avtotest.md), [T-220](T-220-scenarii-10-transkript-roznichnogo-dialoga-i-11.md)

## Что сделать
1. Запись кассет на репетиции с реальными GigaChat-3-Ultra/Lightning для сценариев 8, 8b, 9, 9b и «Надиктовать»; экспорт в data/cassettes/*.jsonl (≤ 50 МБ суммарно); demo_assets kind=cassette с checksum.
2. make cassettes-record SCENARIO=…; тест test_cassettes_fresh: при смене prompt_version кассеты помечены stale и CI предупреждает.
3. Фикстуры pytest подключают кассеты автоматически для маркера scenario.

## Критерии приёмки
- [ ] Автотесты сценариев 8–9 зелёные без сети; кассеты без секретов/ПДн.
- [ ] Смена версии промпта помечает кассеты stale (тест).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest -m scenario
make cassettes-record SCENARIO=qr_fee_public_review
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
