# T-013 — Продукты, системы, команды, каналы

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Refs` (справочники) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Модель банка из ТЗ 3.3–3.6.

## Разделы ТЗ (docs/TZ.md)
§3.3, §3.4, §3.5, §3.6

## Контракты
- `db/schema.sql: products, systems, teams, team_systems, channels`

## Зависимости
- Зависит от: —
- Блокирует: [T-014](T-014-kody-oshibok-tipy-signalov-pravila-marshrutizaci.md), [T-015](T-015-shablony-uvedomlenij-spravochnik-podarkov-stavki.md), [T-017](T-017-produkty-klientov-i-14-dnej-operacij.md), [T-019](T-019-biblioteka-tekstov-signalov.md), [T-036](T-036-emulyator-komand-i-cifrovoj-sled-incidenta.md), [T-184](T-184-taksonomiya-missellinga-i-rule-detektor-predvari.md)

## Что сделать
1. data/products.yaml: 4 продукта с тарифами и акциями (в т. ч. промо-ставка вклада для ключевого сценария, срок действия).
2. data/systems.yaml: 12 систем со слоями; data/teams.yaml: 10 команд со speed_profile (часы взятия, множитель фикса, p_clarify, p_sla_breach, p_regression=0.12) и синтетическими руководителями; связь команда↔системы.
3. data/channels.yaml: 8 каналов с подтипами, identifies_client, is_public.
4. Загрузчик scripts/seed/refs_bank.py.

## Критерии приёмки
- [ ] Загружается идемпотентно; все FK разрешаются.
- [ ] Каждая система закреплена хотя бы за одной командой.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
python scripts/seed/refs_bank.py --check
```

## Отчёт субагента
Ветка main, коммит B21. `data/products.yaml` (4 продукта: тарифы, акция PROMO-DEP-14 ставка 14 % vs базовая 9,5 %, перечень op_type по enum `sim/op`), `data/systems.yaml` (12 систем по слоям), `data/teams.yaml` (12 команд, speed_profile: take_hours, fix_days_factor, p_clarify, p_sla_breach, p_regression 0.12; team_systems), `data/channels.yaml` (11 каналов с подтипами), `data/error_codes.yaml` (16 кодов ошибок, вкл. PROC-QR-FEE-CHARGED, + 10 типов сигналов), `data/sla.yaml` (матрица 3×3 по ТЗ 8.2 с днями отчётов и take_hours 2/4/8; 20 правил маршрутизации), `data/templates/notifications.yaml` (Jinja2 по сегментам → notification_templates на все каналы), `data/llm_profiles.yaml`, `data/dcltv_rates.csv` (31), `data/gifts.yaml` (каталог + economics_settings), `data/ingest_sources.yaml`. Загрузчики `refs.py::seed_catalogs/seed_economics/seed_templates` идемпотентны. Время: ~40 мин.
