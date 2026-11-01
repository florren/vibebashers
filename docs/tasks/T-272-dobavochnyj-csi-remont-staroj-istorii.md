# T-272 — Добавочный CSI-ремонт старой истории

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Signals` (тексты и предыстория сигналов) |
| Оценка | M (1–2 дня) |
| Волна | 9 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `done` |

## Цель
GitHub #103: покрытие 480/480 без сброса данных и решений.

## Разделы ТЗ (docs/TZ.md)
§4.4, §4.6

## Контракты


## Зависимости
- Зависит от: [T-270](T-270-bezopasnyj-povtornyj-seed-i-pg-dump-v-docker.md)
- Блокирует: [T-275](T-275-avtomaticheskij-csi-remont-posle-baseline-restor.md)

## Что сделать
1. Dry-run и атомарный repair через normalizer только для недостающих CSI baseline.
2. Идемпотентность, отказ при чужих пробелах, сохранность всех прежних строк/решений и baseline.
3. Backup, проверка копии и применение на стенде без reset.

## Критерии приёмки
- [ ] Старый набор имеет 480/480; добавлены только недостающие CSI.
- [x] Повтор no-op, ошибка откатывает всю транзакцию; решения и часы сохранены.
- [x] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make lint && make test
repair_csi.py dry-run / --apply / повтор на копии и стенде
```

## Отчёт субагента
Ветка `codex/idle-generation-csi-repair`, 30.10.2026. Cross-layer согласован. Контракты не менялись.
Полный make lint && make test: unit 588, integration 137, scenarios 22 passed;
compliance отдельно 31 passed. Frontend 132 passed, обе сборки. Подробности —
[доказательства и SQL](../benchmarks/idle-generation/README.md).

Реализация и замеры: ADR-0019, docs/benchmarks/idle-generation/csi-copy.json.
Копия реального стенда: +40 CSI, 480/480; повтор +0; digest прежних строк всех 85 таблиц совпал.
