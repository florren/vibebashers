# T-051 — API и UI профилей LLM и ключей

| Поле | Значение |
|---|---|
| Эпик | E4 LLM-слой |
| Субагент | `SA-LLM` (LLM-слой) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 2 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Управление провайдерами из настроек: роли main/fast/twin, активность, ключи, лимиты.

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 5, §5.2

## Контракты
- `api/openapi.yaml: settings/llm-profiles, settings/llm-keys, setup/test-llm`

## Зависимости
- Зависит от: [T-050](T-050-rate-limiter-byudzhety-fallback-i-maskirovanie-s.md), [T-010](T-010-ui-mastera-nastrojki-9-shagov-i-ekran-nastrojki.md)
- Блокирует: —

## Что сделать
1. CRUD профилей и ключей по контракту (ключ только writeOnly, шифрование pgp_sym_encrypt APP_SECRET).
2. UI-вкладка: таблица профилей с ролями, кнопка «Проверить», индикаторы остатка токенов/лимитов/баланса, предупреждения.

## Критерии приёмки
- [ ] Смена main-профиля применяется к следующему запуску агента без рестарта.
- [ ] Ключ не возвращается ни одним API.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_llm_settings_api.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
