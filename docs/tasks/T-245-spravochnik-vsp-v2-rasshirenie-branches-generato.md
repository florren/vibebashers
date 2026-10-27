# T-245 — Справочник ВСП v2: расширение branches, генератор сети ≈ 240 ВСП, BranchDirectoryProvider (synthetic | snapshot_file), история сети

| Поле | Значение |
|---|---|
| Эпик | E20 CSI-аналитика и сеть ВСП [ЕТЗ] |
| Субагент | `SA-Clients` (клиенты и операции) |
| Оценка | M (1–2 дня) |
| Волна | 8 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

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
- [ ] Сид создаёт ≈ 240 ВСП, `test_coverage` не регрессирует, сценарии 9–10 зелёные.
- [ ] Режим `snapshot_file` загружает файл-образец без сетевых вызовов (проверка заглушкой сети).
- [ ] Два запуска с одним сидом дают одинаковую сеть.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make seed PROFILE=lite && pytest backend/tests/integration/test_branches_v2.py
pytest backend/tests/unit/test_branch_provider.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
