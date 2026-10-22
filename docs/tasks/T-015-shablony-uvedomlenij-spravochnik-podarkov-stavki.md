# T-015 — Шаблоны уведомлений, справочник подарков, ставки dCLTV, параметры экономики

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Refs` (справочники) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Тексты коммуникаций по сегментам и каналам, подарки, ставки калькулятора.

## Разделы ТЗ (docs/TZ.md)
§8.4, §8.5, §11.1, §14.4, §0.4

## Контракты
- `db/schema.sql: notification_templates, gift_catalog, dcltv_rates, economics_settings`

## Зависимости
- Зависит от: [T-012](T-012-segmenty-psihotipy-doli-psihotipov-po-segmentam.md), [T-013](T-013-produkty-sistemy-komandy-kanaly.md)
- Блокирует: [T-020](T-020-predystoriya-signalov-incidentov-statusov-artefa.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md), [T-078](T-078-podarki-raschet-zadachi-vydacha-posle-podtverzhd.md), [T-131](T-131-raschet-ekonomiki-dcltv-po-incidentu.md), [T-157](T-157-yazyk-kommunikacij-s-klientom-i-en-shablony.md)

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
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
