# T-015 — Шаблоны уведомлений, справочник подарков, ставки dCLTV, параметры экономики

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Refs` (справочники) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Тексты коммуникаций по сегментам и каналам, подарки, ставки калькулятора.

## Разделы ТЗ (docs/TZ.md)
§8.4, §8.5, §11.1, §14.4, §0.4

## Контракты
- `db/schema.sql: notification_templates, gift_catalog, dcltv_rates, economics_settings`

## Зависимости
- Зависит от: [T-012](T-012-segmenty-psihotipy-doli-psihotipov-po-segmentam.md), [T-013](T-013-produkty-sistemy-komandy-kanaly.md)
- Блокирует: [T-020](T-020-predystoriya-signalov-incidentov-statusov-artefa.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md), [T-078](T-078-podarki-raschet-zadachi-vydacha-posle-podtverzhd.md), [T-131](T-131-raschet-ekonomiki-dcltv-po-incidentu.md), [T-157](T-157-yazyk-kommunikacij-s-klientom-i-en-shablony.md), [T-236](T-236-spravochnik-product-lines-15-napravlenij-data-pr.md)

## Что сделать
1. data/templates/*.j2: коды ack_received, proactive_fault, clarify_request, progress_update, resolved, gift_offer, public_reply, dm_invite, closure_ack — для каналов push/sms/email/chat/social_reply/telegram_bot/tracking_page, ru и en, вариации тона по сегментам (mass/premium/vip/ultra_vip минимум).
2. Список запрещённых формулировок data/forbidden_phrases.yaml (обещания сроков вне SLA, обвинения клиента, внутренние названия систем).
3. data/gifts.yaml: bonus_points (300/600/1000 по критичности, +200 за повтор, cap 1000), lounge_pass, restaurant_special, business_class_discount (vip/ultra_vip, requires_hitl), personal_call; вымышленные партнёры.
4. data/dcltv_rates.csv: все ставки из ТЗ 0.4/14.4 с maps_to; bank_average 4050 как fallback; economics_settings по умолчанию из ТЗ 14.4.

## Критерии приёмки
- [ ] Шаблоны рендерятся Jinja2 без ошибок для всех сегментов на двух языках (тест).
- [ ] Ставки совпадают с ТЗ 0.4 до копейки.
- [ ] Подарки vip/ultra_vip помечены requires_hitl.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_templates.py backend/tests/unit/test_rates.py
```

## Отчёт субагента
Сверка 27.10.2026 (T-261): `data/templates/notifications.yaml` (вместо `*.j2`), `data/gifts.yaml`, `data/dcltv_rates.csv` (30 ставок, `bank_average` 4 050) и `economics_settings` существуют и используются. Остаток: список запрещённых формулировок живёт в коде `app/agent/policies.py` (`forbidden_phrases`), а не в `data/forbidden_phrases.yaml` — при следующем касании вынести в данные (правило: бизнес-правила — данные).

Ревизия `codex/T-015-communication-catalogs`:
- Прежние18 фраз перенесены в `data/forbidden_phrases.yaml`; сопоставление/порядок сохранены. Добавлен отдельный список10 однозначных технических идентификаторов из `systems.yaml`; проверяются границы токена, регистр не важен. Обычное processing и клиентские error codes не блокируются. Неисправная конфигурация завершает загрузку ошибкой, без отключения фильтра молча. Каталог загружается при старте backend.
- Добавлены ru/en dm_invite/closure_ack и csi_survey в существующий wildcard seed. SQL fallback теперь допускает только заданный сегмент либо общий шаблон, не чужой сегмент. Денежные/HITL функции и лимиты не менялись; rule.requires_hitl=true для трёх партнёрских подарков отражает уже существующую проверку runtime.
- Существующий YAML каталог сохраняется: проверена эквивалентность всех его subject/body строгому Jinja rendering с полным набором переменных. Полная матрица9 кодов×12 канонических каналов×7 сегментов×2 языков и fallback push/sms/social_reply/tracking_page проверена без расширения channel enum/FK. Эти четыре legacy delivery-name не являются каноническими каналами текущего контракта.
- Проверены Decimal значения30 исходных ставок ТЗ0.4 без потери долей копейки; CSV дополнительно сохраняет существующий notifications alias. Маппинг ставок и economics_settings не менялись.

Незавершённая финансовая граница (требует согласования): ТЗ14.4 указывает misselling_case_cost_rub=4050, в gifts.yaml25000; notification_gw/promo_engine должны использовать bank_average4050, текущий CSV привязывает их к292.005/373.005. До сверки последних решений/ADR и согласования эти поля сохранены. Предложение точечного diff подготовлено отдельно и не включено в рабочие изменения. Карточка не объявляется done.

Проверки: адресные unit и настоящая PostgreSQL-регрессия на отдельной cx_t015_catalogs проходят; PostgreSQL проверяет seed, ru/en×4 основных сегмента, fallback и partner rule. Ruff/format/mypy проходят. Полный unit suite собственного worktree: 770 passed / 18 skipped (37 новых unit-тестов); адресная PostgreSQL-регрессия: 1 passed. contracts_check:44 схемы/161 путь, ruff/format/mypy и git diff --check — success. Полный CI/merge выполняет основной агент.
