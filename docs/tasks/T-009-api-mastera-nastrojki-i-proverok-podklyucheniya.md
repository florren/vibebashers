# T-009 — API мастера настройки и проверок подключения

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-Infra` (инфраструктура, установка, realtime) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Бэкенд для 9 шагов мастера: сохранение, проверка LLM и бота, запуск генерации данных.

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 1, §5.2, §11.3

## Контракты
- `api/openapi.yaml: setup/*`

## Зависимости
- Зависит от: [T-004](T-004-karkas-fastapi-konfig-logirovanie-oshibki-health.md), [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md), [T-016](T-016-generator-klientov-profili-lite-demo-stress.md)
- Блокирует: [T-010](T-010-ui-mastera-nastrojki-9-shagov-i-ekran-nastrojki.md)

## Что сделать
1. GET /api/setup/status, PUT /api/setup (частичное сохранение шагов в settings), POST /api/setup (завершение).
2. POST /api/setup/test-llm: вызов провайдера с коротким промптом, измерение латентности, определение supports_tools/stream, чтение квот (OpenRouter /api/v1/key, остаток токенов GigaChat).
3. POST /api/setup/test-tgbot: getMe через aiogram/HTTP.
4. POST/GET /api/setup/generate: фоновая задача сида с прогрессом и логом, матрица покрытия по завершении.

## Критерии приёмки
- [ ] Все пути тега setup реализованы по контракту.
- [ ] Неверный ключ LLM возвращает ok=false и понятную ошибку, не 500.
- [ ] Генерация lite из мастера завершается ≤ 30 с.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_setup_api.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
