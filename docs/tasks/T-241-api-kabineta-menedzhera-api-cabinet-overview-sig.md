# T-241 — API кабинета менеджера: /api/cabinet/overview|signals, пресеты ролей X-Cx-Role, режимы soft/strict, /api/roles

| Поле | Значение |
|---|---|
| Эпик | E19 Кабинет менеджера продукта и продуктовый разрез [ЕТЗ] |
| Субагент | `SA-Analytics` (API кабинета, CSI и ВСП, индекс CX [ЕТЗ]) |
| Оценка | L (3–4 дня) |
| Волна | 8 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Серверная часть кабинета (ТЗ 24.1, 24.4–24.5): KPI, ряды, источники, топ-5 регионов, список сигналов — одним быстрым запросом.

## Разделы ТЗ (docs/TZ.md)
§24.1, §24.4, §24.5, §14.4, §16.4

## Контракты
- `api/openapi.yaml: /api/cabinet/overview, /api/cabinet/signals, /api/roles`
- `contracts: v_cabinet_kpi`

## Зависимости
- Зависит от: [T-237](T-237-kontrakty-kabineta-csi-i-vsp-migraciya-0005-open.md), [T-132](T-132-api-svodnoj-ekonomiki-i-metrik-dashborda.md), [T-238](T-238-klassifikaciya-po-napravleniyu-i-urovnyu-signala.md)
- Блокирует: [T-242](T-242-ekran-kabinet-menedzhera-produkta-cabinet-kpi-ka.md), [T-244](T-244-otchet-po-napravleniyu-dlya-cheloveka-get-api-ca.md)

## Что сделать
1. `backend/app/analytics/cabinet.py`: KPI (сигналов, доля негатива, доля критических, потеря и предотвращённое по `incident_economics` для инцидентов направления), 30 дней по дням, 12 месяцев (`product_signal_history` + живые), источники (`signals.meta.source_platform`), топ-5 регионов; параметры `product_line`, `period`, `run_id`.
2. Пресеты ролей: middleware читает `X-Cx-Role`/`X-Cx-Product-Line` (по умолчанию `cx_lead`); `settings.cabinet.visibility = soft|strict` (в `strict` чужие направления не отдаются, 403 с понятным текстом); `GET /api/roles` отдаёт пресеты и подписи.
3. `GET /api/cabinet/signals`: сортировка по уровню/дате/региону, фильтры (регион, статус, канал, красные слова), пагинация; `actor_role` в записях `human_decisions` и `incident_status_history`.
4. Тяжёлые агрегаты — через представления `v_*` и индексы (правило 11); p95 ≤ 300 мс на demo; тесты: strict/soft, согласованность с экономикой 14.4, отсутствие чужих данных.

## Критерии приёмки
- [ ] `overview` отвечает ≤ 300 мс (p95) на профиле demo; значения совпадают с `incident_economics` (тест).
- [ ] В `strict` данные других направлений недоступны ни одним эндпоинтом кабинета.
- [ ] Нет ORM-циклов в агрегатах (EXPLAIN-тест).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_cabinet_api.py
curl -s -H 'X-Cx-Role: product_manager' -H 'X-Cx-Product-Line: deposits' localhost:8000/api/cabinet/overview | jq '.kpi'
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
