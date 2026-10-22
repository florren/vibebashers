# T-179 — Сценарий 8 «Комиссия за QR-оплату и публичный отзыв»: YAML, автотест, замер латентности

| Поле | Значение |
|---|---|
| Эпик | E15 Внешние площадки и автономный возврат [BRD] |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Автопроверяемый ключевой сценарий BRD-1 с ожиданиями по шагам, балансу, ответу и времени (ТЗ 18 п. 8, 19 п. 18–19).

## Разделы ТЗ (docs/TZ.md)
§18, §19

## Контракты
- docs/TZ.md 18 сценарий 8
- `backend/tests/scenarios/fixtures/scenario_08.yaml`

## Зависимости
- Зависит от: [T-174](T-174-bystryj-put-agenta-uslovnoe-rebro-act-instant-st.md), [T-175](T-175-instrumenty-refund-fee-find-affected-clients-get.md), [T-176](T-176-priemnik-otzyvov-external-posts-replies-instrume.md), [T-038](T-038-dvizhok-scenariev-yaml-i-7-demo-scenariev.md), [T-198](T-198-kassety-scenariev-8-9-i-avtotesty-na-nih-procedu.md)
- Блокирует: [T-204](T-204-demo-skript-7-8-i-3-5-minut-readme-razdelov-zhiv.md)

## Что сделать
1. YAML: клиент mass Воронеж public_emotional, карта **** 4512, QR-оплата 3 200 ₽ с комиссией 450 ₽; пост от @ivan_v; ожидания: identified 0,9+, RULE-QR-FEE-001 matched, refund 450, incident fee_refund closed, reply под постом, gift 300, массовый инцидент tech_fault с HITL (37 пострадавших).
2. Вариант 8b без идентификации: пост без карты и незнакомый ник → публичное приглашение в личный канал.
3. Тест на кассете (детерминирован) и live-тест с замером p50/p95 (маркер live, не в CI).
4. Сброс к baseline возвращает клиента в состояние «комиссия списана».

## Критерии приёмки
- [ ] Автотест зелёный в CI на кассете ≤ 60 с.
- [ ] Отчёт live-замера в PR: p50 ≤ 10 с, p95 ≤ 15 с.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=qr_fee_public_review
pytest backend/tests/scenarios/test_scenario_08_qr_fee.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
