# T-152 — LICENSES.md и источники данных

| Поле | Значение |
|---|---|
| Эпик | E12 Документация и защита |
| Субагент | `SA-Docs` (документация) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 5 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `review` |

## Цель
Подтверждение открытости стека и данных (требование заказчика).

## Разделы ТЗ (docs/TZ.md)
§5.3, §16.4, §21

## Контракты
- AGENTS.md §2

## Зависимости
- Зависит от: [T-001](T-001-skelet-repozitoriya-makefile-env-example-pre-com.md), [T-011](T-011-spravochnik-subektov-i-gorodov-rf-svg-karta.md)
- Блокирует: —

## Что сделать
1. Автогенерация таблицы зависимостей (pip-licenses, license-checker) + ручной раздел по шрифтам, карте, иконкам; проверка в CI на запрещённые лицензии.

## Критерии приёмки
- [ ] Нет GPL/AGPL/SSPL/source-available зависимостей; CI падает при появлении.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make licenses-check
```

## Отчёт субагента
Ветка `codex/T-152-licenses`: строгий SPDX gate и генерируемый THIRD_PARTY_LICENSES.md для 89 Python/437 npm distributions, runtime/dev/platform-only. Версии и metadata закреплены; platform-only wheel получены без установки из официального PyPI и сверены SHA256 с uv.lock. Непроверенные identifiers/WITH, отсутствующие metadata и дрейф inventory приводят к ошибке. Legacy notices адресно проверены по версии и hash; LGPL не смешивается с GPL. Дополнительных dependencies нет.

Обнаруженный GPL-3.0-or-later dev-пакет pglast 8.7 удалён с согласования основного агента; остальные версии lock не менялись. SQL проверяется настоящим PostgreSQL16 в db job: schema и динамический полный список migrations/*.sql, повторное применение. mirror.yml не менялся. Ручные notices шрифтов, карты, Vosk и TLS описаны в docs/LICENSES.md.

Проверки: 25 адресных regression-тестов passed; полный unit suite собственного worktree — 758 passed / 18 skipped; make licenses-check — 526 distributions, success; contracts_check — success. ruff check/format backend app/tests и новых scripts — success; git diff --check, owners L1 и YAML workflow parse — success. Полный make lint/make test, PostgreSQL CI и merge выполняет основной агент после интеграции; карточка не объявлена done до этих проверок.
