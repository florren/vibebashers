# T-245 — Справочник ВСП v2: расширение branches, генератор сети ≈ 240 ВСП, BranchDirectoryProvider (synthetic | snapshot_file), история сети

| Поле | Значение |
|---|---|
| Эпик | E20 CSI-аналитика и сеть ВСП [ЕТЗ] |
| Субагент | `SA-Clients` (клиенты и операции) |
| Оценка | M (1–2 дня) |
| Волна | 8 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `done` |

## Цель
Сеть ВСП без внешних вызовов (ТЗ 25.4, 20.7 № 35, 54).

## Разделы ТЗ (docs/TZ.md)
§25.4, §6.6, §4.4

## Контракты
- `data/branches.yaml`
- `data/regions.csv (okato)`
- `data/import/branches/`
- `db: branches, employees, branch_network_history`

## Зависимости
- Зависит от: [T-237](T-237-kontrakty-kabineta-csi-i-vsp-migraciya-0005-open.md)
- Блокирует: [T-247](T-247-korpus-csi-csi-v1-300-zhalob-csi-visits-agg-znam.md), [T-248](T-248-api-analitiki-csi-i-vsp-korrelyacii-scatter-dolz.md), [T-250](T-250-karta-sloj-vsp-markery-po-tipam-klasterizaciya-k.md)

## Что сделать
1. Расширить `data/branches.yaml`/генератор: тип (`flagship|standard|additional|mobile`), статус, координаты (вокруг центроидов регионов и городов, с разбросом), синтетический адрес и режим работы, даты открытия/закрытия, `product_line_codes[]`; ≈ 240 ВСП по субъектам РФ, ≈ 8 % закрыты, 10 исходных отделений и их коды сохранены (сценарии 9–10).
2. `BranchDirectoryProvider`: `synthetic` (по умолчанию, детерминированный от `sim_state.seed`) и `snapshot_file` (ручная выгрузка в `data/import/branches/`, парсинг CSV/JSON, без сети); SOAP-клиента и cron нет.
3. Столбец `regions.okato` и таблица соответствия в `data/regions.csv`; `branch_network_history` за 12 месяцев (открытия и закрытия); сотрудники: образование и стаж (синтетика).
4. Идемпотентность сида, пересоздание baseline; `test_no_pii` и отсутствие реальных адресов/брендов.

## Критерии приёмки
- [x] Сид создаёт ≈ 240 ВСП, `test_coverage` не регрессирует, сценарии 9–10 зелёные.
- [x] Режим `snapshot_file` загружает файл-образец без сетевых вызовов (проверка заглушкой сети).
- [x] Два запуска с одним сидом дают одинаковую сеть.
- [x] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make seed PROFILE=lite && pytest backend/tests/integration/test_branches_v2.py
pytest backend/tests/unit/test_branch_provider.py
```

## Отчёт субагента
Ветка `feat/T-245-branch-directory`, база main после #68 (`3bebfa4`).

Реализованы BranchDirectoryProvider и провайдеры synthetic/snapshot_file без сетевых вызовов. Детерминированные 240 ВСП по 89 регионам, 19 закрыты (7,9 %), четыре типа; десять исходных кодов и 60 их сотрудников сохранены, включая 0042/места 3 и 5 сценариев 9–10. Новые адреса явно учебные, сотрудники синтетические: 1440 записей с образованием, датами найма и начала должности. Генератор дополнительных ВСП не меняет RNG клиентов. Seed явно задаётся CLI, по умолчанию из sim_state.seed.

CSV/JSON snapshots ограничены data/import/branches/, 10 MB/10 000 строк; примеры синтетические. Ошибки с номером строки; проверяются город/регион, направление, дубли, статусы и даты. Сценарные отделения не заменяются, имена руководителей из реестра не переносятся. При смене источника отсутствующие записи закрываются, не удаляются; исторические FK сохраняются. Сеть за 12 месяцев агрегируется по всем сохранённым ВСП. Режим источника и as-of сохраняются в settings.branch_directory.

ОКАТО в regions.csv и БД: 85 подтверждённых кодов, включая отдельные коды Ненецкого АО/ХМАО/ЯНАО по первичному источнику Росстата (ссылка в data/README.md). Для 90/93/94/95 оставлены NULL, выдуманные соответствия не используются. Контракты БД/API не менялись. API /branches и /branches/network реализованы по существующим путям: фильтры, курсор, ограничения параметров, Cache-Control 24 часа, маркировка источника; Telegram chat ID наружу не выдаётся.

Проверено: unit-провайдера 9 passed; integration ветки/coverage/baseline 10 passed, включая восстановление точных строк branches/employees/branch_network_history из dump. Первый полный pytest выявил только старое ожидание 60 сотрудников: проверка обновлена на точные 1440 и отдельно сохранён инвариант 60 в исходных отделениях; остальные 525 passed/20 skipped, сценарии 9–10 не регрессировали. Node22: lint/tsc/33 vitest/build; generated API types без diff. Contracts41/149, OpenAPI175/175, i18n1032, validate_refs и owners --allow-cross зелёные. Итоговый make lint test зелёный: 405 unit passed/16 skipped, 69 integration passed/2 skipped, 22 scenarios passed/2 skipped; сценарии 9–10 и строгий replay сценария 8 не регрессировали. Итоговый CI и merge — в PR T-245.
