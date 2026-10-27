# T-236 — Справочник product_lines (15 направлений): data/product_lines.yaml, маппинг на ставки dCLTV, команды, продукты

| Поле | Значение |
|---|---|
| Эпик | E19 Кабинет менеджера продукта и продуктовый разрез [ЕТЗ] |
| Субагент | `SA-Refs` (справочники) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 7 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Нейтральный справочник 15 направлений ЕТЗ (ТЗ 24.2) как данные, а не код.

## Разделы ТЗ (docs/TZ.md)
§24.2, §14.4, §3.3

## Контракты
- `data/product_lines.yaml`
- `data/dcltv_rates.csv (только чтение)`

## Зависимости
- Зависит от: [T-013](T-013-produkty-sistemy-komandy-kanaly.md), [T-015](T-015-shablony-uvedomlenij-spravochnik-podarkov-stavki.md)
- Блокирует: [T-237](T-237-kontrakty-kabineta-csi-i-vsp-migraciya-0005-open.md), [T-238](T-238-klassifikaciya-po-napravleniyu-i-urovnyu-signala.md), [T-240](T-240-korpus-product-lines-v1-i-istoriya-teksty-po-15.md)

## Что сделать
1. `data/product_lines.yaml`: код, `name_ru`, `name_en`, `rate_code`, `owner_team_code`, `owner_is_proxy`, `product_codes[]`, `sort_order`, доля демо-датасета (54 отзыва по таблице ТЗ 24.2).
2. Правило отсутствующей ставки: `business_banking` и `fraud_security` → `bank_average` с флагом `rate_is_fallback`; отображение ставки с банковским округлением до 2 знаков.
3. Валидатор справочника в `scripts/seed/` (все `rate_code` существуют в `dcltv_rates.csv`, команды существуют в `teams.yaml`, коды `products` существуют), тест соответствия и отсутствия реальных брендов.
4. Раздел «Справочник направлений» в `data/README.md` (источник, лицензия, замены брендов).

## Критерии приёмки
- [ ] Валидатор зелёный; в файле нет реальных названий банков и сервисов.
- [ ] Ставки не дублируются в справочнике — берутся из `dcltv_rates.csv`.
- [ ] Таблица ТЗ 24.2 и YAML совпадают (проверка тестом).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_product_lines_ref.py
python scripts/seed/validate_refs.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
