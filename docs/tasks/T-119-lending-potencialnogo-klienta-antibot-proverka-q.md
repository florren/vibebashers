# T-119 — Лендинг потенциального клиента, антибот-проверка, QR

| Поле | Значение |
|---|---|
| Эпик | E9 Лендинг, трекинг, Telegram-бот |
| Субагент | `SA-Landing` (лендинг и трекинг) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Экран 6: форма обращения для неидентифицированного клиента с выдачей ссылки трекинга и QR.

## Разделы ТЗ (docs/TZ.md)
§11.2, §12.2 экран 6

## Контракты
- `api/openapi.yaml: public/claim, public/captcha`

## Зависимости
- Зависит от: [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md), [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md)
- Блокирует: [T-120](T-120-stranica-trekinga-obrascheniya-i-dopolnenie.md), [T-143](T-143-playwright-smouk-i-vizualnaya-regressiya.md), [T-156](T-156-polnye-slovari-ru-en-i-proverka-i18n.md), [T-206](T-206-nadiktovat-zhalobu-voiceinput-v-rezhime-pokaza-i.md), [T-269](T-269-izolirovannyj-anonimnyj-chat-9999-i-tunnel-tuna.md)

## Что сделать
1. Страница /landing в стиле ТЗ 12.1 без брендирования: описание, форма (контакт, регион/город, продукт, текст, согласие), арифметическая captcha, лимит 5 обращений/мин с IP.
2. Backend: создание сигнала origin=landing с external_contact, tracking_token (secrets.token_urlsafe(24)), QR SVG (python qrcode) ссылки трекинга.
3. Экран успеха с public_id, ссылкой, QR и кнопкой «Открыть трекинг».

## Критерии приёмки
- [x] Сценарий 4 через лендинг проходит до ответа.
- [x] Без captcha/согласия — 422 с понятным текстом.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/landing.spec.ts
```

## Отчёт субагента
Ветка `feat/T-119-landing-public` от main `4a52284`. Коммит `4a5086f`. PR https://github.com/florren/vibebashers/pull/57. Чекбоксы приёмки не отмечаются: их заново пишет `scripts/gen_tasks.py`, и CI сравнивает карточку с генератором.

Закрыты `POST /api/public/claim`, `GET /api/public/captcha`, `GET/POST /api/public/track/{token}`, `GET /api/public/bot/qr` и `POST /api/internal/tgbot/inbound`. Сигнал создаётся только через `from_landing` / `from_bot` и `create_signal`. UI — страница `/claim` (форма, капча, успех с номером, ссылкой и QR). Страница `/track` и событие `signal.appended` не делались. Контракты не менялись.

Коды `landing`, `telegram_bot` и `track_append` отсутствуют в `data/ingest_sources.yaml`, а `ingest_messages.source_code` ссылается на `ingest_sources`. Перед записью сигнала эти три кода вставляются идемпотентно (`on conflict do nothing`), иначе внешний ключ рвёт приёмку.

Проверка шага 3: `cd backend && .venv/bin/pytest -q tests/integration/test_public_claim.py` — код 0, `1 passed`. Сценарий 4 и полный `make test` не запускались. `make lint` на этой ветке красный из-за чужого `ruff format --check` (файлы вне пакета); мои модули `ruff` и `mypy` проходят.

Сверка 27.10.2026 (T-261): статус `todo` → `in_progress` — основная часть слита в PR #57 и #59; остаток по отчёту выше: страница `/track` и событие `signal.appended`.


### Ревизия 01.11.2026 — отдельная T-119

Ветка `codex/T-119-public-claim` от `f594c43`; зависимая ветка T-120 содержит страницу трекинга, дополнения и SMTP. T-119 добавляет публичные `/landing` и `/claim`, отдельную оболочку ru/en без операторских WebSocket/настроек, серверный VoiceInput с `voice_meta`, доступные имена полей и безопасный GET tracking API. Ошибки/HTTP/Uvicorn logs не раскрывают capability token; no-store/no-referrer/noindex применены к публичной истории, включая SPA referrer policy. Уведомления ограничены деревом сигналов владельца токена, чужие уведомления общего инцидента не выдаются.

Самостоятельно работают форма, captcha/consent/лимит, нормализатор, немедленный dispatch агента, success public_id/QR/ссылка и GET API истории. Маршрут `/track/:token` добавляет следующий stacked T-120: первая ветка показывает правильную ссылку, но переход требует слияния T-120. Это явная зависимость карточек; промежуточного stub или mock production API нет. Сценарий 4 соответствует `anonymous_handoff`: реальный API/normalizer/graph с mock LLM создаёт инцидент и отправляет ack_received; это не финальное решение проблемы.

Контракты, схема и зависимости не менялись. Скриншоты формы ru/en/light/dark: `docs/screenshots/public-tracking/landing-{ru,en}-{light,dark}.png`. Самостоятельная ветка проверена: make lint (147 frontend tests, Ruff, mypy, OpenAPI drift), обе production-сборки, 6 backend privacy/claim/scenario4 integration/unit tests, 5 Playwright cases формы (ru/en/light/dark и выдача ссылки). Статус in_progress сохраняется до полного DoD, включая отдельно не выполненную live GigaChat проверку.
