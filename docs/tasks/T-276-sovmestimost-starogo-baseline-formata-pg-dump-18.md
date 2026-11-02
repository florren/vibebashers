# T-276 — Совместимость старого baseline формата pg_dump 18

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-Infra` (инфраструктура, установка, realtime) |
| Оценка | M (1–2 дня) |
| Волна | 9 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
GitHub #108: отдельная задача по согласованию; старый файл стенда не читается pg_restore 16 и содержит прежнюю схему.

## Разделы ТЗ (docs/TZ.md)
§4.6, §16.2

## Контракты


## Зависимости
- Зависит от: [T-270](T-270-bezopasnyj-povtornyj-seed-i-pg-dump-v-docker.md), [T-275](T-275-avtomaticheskij-csi-remont-posle-baseline-restor.md)
- Блокирует: —

## Что сделать
1. Спроектировать безопасную совместимость формата/миграций на изолированной PG16 без сброса рабочего стенда.
2. Не скрывать SQL-ошибки pg_restore exit=1; сохранить исходный архив, checksum и recovery.

## Критерии приёмки
- [x] Путь старого архива проверен на копии; формат и схема совместимы до применения к стенду.
- [x] При ошибке нет ложного успеха и потери данных/исходного файла.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
Настоящий старый архив, изолированная PG16 и проверка rollback/повторов
```

## Отчёт субагента
Ветка `codex/T-276-legacy-baseline`, source fix `e586ed0`.
Настоящий исторический архив pg_dump18 (SHA `efd316e8…9193`) проверен на отдельной
копии в двух собственных scratch PG16; original/canonical/sidecars не менялись.
Исправлен пропуск canonical COMMENT sim_runs без изменения contracts/models;
real-DB regression проверяет comment и динамический текущий Alembic head.

Actual conversion, два restore, CSI 480/480 (повтор added0), schema drift check,
183 FK без orphan, SQL rollback/retry и overwrite/nonempty refusal проверены.
`make lint` green; полный sequential `make test`: **1423 backend passed/24 skipped,
173 frontend passed**. Новые executable строки: 4/5 = 80% coverage.
Licenses gate green, 530 distributions. Карточка остаётся
in_progress до PR/CI/review/merge. Future schema0011/12/13 не проверялись, working
stand не восстанавливался; real external LLM не вызывались.

Подробности и recovery: [T-276 proof](../reviews/T-276-legacy-baseline.md),
[JSON](../reviews/T-276-legacy-baseline-proof.json).
