# T-014 — Коды ошибок, типы сигналов, правила маршрутизации, матрица SLA

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Refs` (справочники) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `review` |

## Цель
Словари, на которые опираются классификатор, маршрутизация и SLA.

## Разделы ТЗ (docs/TZ.md)
§7, §8.1, §8.2, §9.3

## Контракты
- `db/schema.sql: error_codes, signal_types, routing_rules, sla_matrix`
- `events/common.schema.json`

## Зависимости
- Зависит от: [T-013](T-013-produkty-sistemy-komandy-kanaly.md)
- Блокирует: [T-018](T-018-predystoriya-sboev-i-logi-sistem.md), [T-019](T-019-biblioteka-tekstov-signalov.md), [T-037](T-037-sla-dvizhok.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md), [T-076](T-076-politiki-hitl-policies-py-i-testy.md)

## Что сделать
1. data/error_codes.yaml: ≥ 25 кодов по системам/продуктам (DEP-TIMEOUT-503, PROMO-RATE-MISMATCH, PROC-DOUBLE-DEBIT, NOTIF-DELAY, APP-LOGIN-FAIL, CARD-ISSUE-STUCK, LIMIT-CALC-ERR, ANTIFRAUD-FALSE-BLOCK …) с default complexity/criticality и описанием.
2. signal_types по ТЗ 7 с base_criticality, requires_hitl, creates_incident.
3. routing_rules: ≥ 15 правил (тип+продукт+система → команды), приоритеты; правило по умолчанию → team_cx.
4. sla_matrix: easy 1/2/3, medium 3/4/5, hard 5/5(+отчёт д3)/10(+отчёты д3,6,9); take_hours по критичности 8/4/2.

## Критерии приёмки
- [x] Матрица SLA в точности как ТЗ 8.2.
- [x] Для каждого error_code есть правило маршрутизации, ведущее в команду, владеющую системой.
- [x] Загрузка идемпотентна.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_refs_routing.py
```

## Отчёт субагента
Ветка `codex/T-014-reference-routing`, ревизия 01.11.2026.

- Каталог расширен с 16 до 25 кодов без удаления прежних идентификаторов. Для всех 25 кодов есть явный маршрут владельцу системы; 40 правил сохраняют приоритеты антифрода/комплаенса и fallback CX. SLA 3×3 и контрольные дни не менялись.
- `scripts/seed/validate_refs.py` проверяет размер/ссылки/enum/булевы признаки и маршруты. Новые `tests/unit/test_refs_routing.py` выполняют настоящий `route_team` для всех кодов, фиксируют матрицу ТЗ и отрицательные случаи конфигурации.
- Устранена причина неидемпотентной загрузки: `seed_catalogs` сохраняет ID правил по неизменному условию вместо полного удаления и повторной вставки. PostgreSQL-регрессия проверяет одинаковые строки/ID при повторной загрузке и восстановление испорченных маршрутов из YAML. Неиспользуемые правила по-прежнему удаляются из проекции источника.
- Проверки в собственной worktree и отдельной PG16: полный `make test` — 766 unit passed /18 skipped, 211 integration passed /2 skipped, 42 scenarios passed /2 skipped, 31 compliance passed; backend всего 1050 passed /22 skipped; frontend 144 passed. `make lint`, обе frontend-сборки, contracts44/161, OpenAPI drift191/191, i18n/owners/diff-check — зелёные.
- После окончательной доработки сохранения ID выполнен отдельный targeted suite (33 unit +1 PostgreSQL):34 passed. Покрытие изменённых исполняемых строк seed/validator —58/71 (81,7%; coverage JSON в локальном `/tmp/t014-coverage.json`).
- Контракты, денежные/HITL политики и рабочая БД не изменялись этим пакетом. CLI проверки и seed запускались только на scratch БД. Общий CI и live GigaChat DoD ещё требуют подтверждения; карточка остаётся review до завершения приёмки.

Contract follow-up 02.11.2026: T-018 выявил непокрытый validator дефект — каталогный ANTIFRAUD-FALSE-BLOCK (префикс9символов) отвергался общей event schema с максимумом6. Подготовлено совместимое расширение префикса до9 без переименования кодов; остальные ограничения сохранены, добавлена проверка всех кодов каталога по контракту. До human review отдельного PR изменение контракта не merge. Первоначальные routing tests проверяли владельцев, но не event schema; это ограничение устранено.
