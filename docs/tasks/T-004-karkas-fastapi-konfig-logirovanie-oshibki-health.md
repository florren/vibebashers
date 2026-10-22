# T-004 — Каркас FastAPI: конфиг, логирование, ошибки, health, settings

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-Infra` (инфраструктура, установка, realtime) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Базовое приложение, на которое навешиваются роутеры по тегам OpenAPI.

## Разделы ТЗ (docs/TZ.md)
§5, §12.2 экран 5

## Контракты
- `api/openapi.yaml: health, settings, refs`

## Зависимости
- Зависит от: [T-001](T-001-skelet-repozitoriya-makefile-env-example-pre-com.md)
- Блокирует: [T-008](T-008-realtime-listen-notify-websocket-hab.md), [T-009](T-009-api-mastera-nastrojki-i-proverok-podklyucheniya.md), [T-031](T-031-simclock-sim-state-i-upravlenie-simulyaciej.md), [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md), [T-181](T-181-sttprovider-i-vosk-vorker-s-modelyu-v-repozitori.md), [T-200](T-200-openapi-1-3-i-json-shemy-v-kode-routery-zaglushk.md)

## Что сделать
1. app/main.py с lifespan (пул БД, LISTEN, фоновые задачи), app/config.py (pydantic-settings), structlog JSON в prod / pretty в dev.
2. Обработчик ошибок RFC 9457 problem+json, валидация 422 с `errors[]`.
3. Роутеры: /api/health, /api/settings (GET/PATCH/export/import), /api/refs/{name}.
4. Заголовок X-Role → request.state.role; middleware времени ответа; CORS только для dev.
5. Swagger UI на /docs; скрипт scripts/check_openapi_drift.py сравнивает сгенерированную схему с contracts/api/openapi.yaml по путям/методам/кодам ответов.

## Критерии приёмки
- [ ] Все пути тегов health/settings/refs из контракта реализованы и совпадают по формам ответов.
- [ ] problem+json на 404/422/500.
- [ ] check_openapi_drift для реализованных тегов проходит.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_health.py
python scripts/check_openapi_drift.py --tags health,settings
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
