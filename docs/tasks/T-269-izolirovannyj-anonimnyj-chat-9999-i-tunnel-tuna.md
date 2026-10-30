# T-269 — Изолированный анонимный чат 9999 и туннель Tuna

| Поле | Значение |
|---|---|
| Эпик | E9 Лендинг, трекинг, Telegram-бот |
| Субагент | `SA-Landing` (лендинг и трекинг) |
| Оценка | L (3–4 дня) |
| Волна | 9 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `done` |

## Цель
Отдельная пользовательская форма/чат с диктовкой, анонимной обработкой и тегом ui_pers_demo. GitHub #98, ADR-0017.

## Разделы ТЗ (docs/TZ.md)
§11.4, §12.2

## Контракты
- `db/migrations/0010_operator_personal_chat.sql`
- `api/openapi.yaml: personal/* и signals tag`

## Зависимости
- Зависит от: [T-119](T-119-lending-potencialnogo-klienta-antibot-proverka-q.md), [T-206](T-206-nadiktovat-zhalobu-voiceinput-v-rezhime-pokaza-i.md), [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md)
- Блокирует: —

## Что сделать
1. Отдельная сборка UI и публичный FastAPI на loopback:9999: без операторской оболочки/API, только своя сессия и ответы штатного агента.
2. Форма со справочниками, свободный текст, локальная диктовка Vosk до 30 с, история диалога в контексте следующих сообщений.
3. ui_pers_demo в normalizer и фильтре Signals; надёжный приём, серверная идемпотентность payload и ограниченные интерактивные слоты.
4. Пассивные защиты, лимиты тела/частоты, same-origin и HttpOnly cookie, honeypot/пауза без CAPTCHA.
5. install.sh запускает Tuna 9999 с заданным поддоменом/лимитом/HTTPS/inspect=false, секрет только из .env; реальные локальные/туннельные проверки.

## Критерии приёмки
- [x] Публичный чат не открывает управление приложением и данные чужой сессии.
- [x] Каждое сообщение анонимно проходит штатный normalizer/агент, имеет тег, получает ответы в чате.
- [x] Диктовка и обе темы/языка работают; защиты не требуют решения CAPTCHA.
- [x] Повторный install не плодит туннели, ключ не попадает в argv/логи/репозиторий; публичный HTTPS проверен.
- [x] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make lint && make test
cd frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build
python scripts/tuna_tunnel.py start --env-file .env; Browser :9999 и публичный HTTPS
```

## Отчёт субагента
Ветка `codex/agent-feedback-public-chat`, GitHub #98. Cross-layer и контракты согласованы заказчиком, включая последующий merge после CI.

Реализованы ADR-0016/0017, миграция 0010, изменения OpenAPI и generated types; для T-268 также новый JSON Schema `agent/operator_feedback` и инструмент `apply_operator_feedback`. Новых Python/npm-зависимостей нет. Подробности проверок и скриншоты: [отчёт](../benchmarks/personal-chat-2026-10-30/README.md). Локальный make lint/test: 719 passed / 21 skipped; frontend 131 passed. Merge выполняется только после CI PR.

T-268: надёжный отдельный разбор, новый план/контекст, атомарность и идемпотентность; исходные деньги и решения не переисполняются. T-269: отдельный :9999, анонимные сообщения/ответы штатного агента, фильтр ui_pers_demo, локальный Vosk и управляемый Tuna из `.env`. Отклонение среды: бесплатный Tuna показывает собственную кнопку «Посетить» до загрузки UI; тариф не менялся.
