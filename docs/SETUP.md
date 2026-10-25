# CX Pulse Control — настройка приложения

Инструкция для того, кто разворачивает стенд. Все команды выполняются из корня репозитория. Время на установку «с нуля» — 10–15 минут.

## 1. Что понадобится

| Компонент | Зачем | Минимум |
|---|---|---|
| Docker + Docker Compose v2 | единственная зависимость для демо-установки | Docker 24+ |
| 4 ГБ RAM, 5 ГБ диска | PostgreSQL + backend (+ фронт внутри образа) | профиль `lite` |
| Ключ GigaChat (необязательно) | «живая» модель вместо встроенной mock-модели | Authorization key из личного кабинета Studio |
| Токен Telegram-бота (необязательно) | канал «потенциальный клиент через бота» | токен от @BotFather |

Без ключей всё работает на встроенной mock-модели: сценарии, HITL, экраны — демонстрируются полностью, тексты ответов шаблонные.

## 2. Установка одной командой

```bash
git clone https://github.com/florren/vibebashers.git && cd vibebashers
cp .env.example .env            # шаг можно пропустить — install.sh создаст .env сам
./install.sh --profile lite     # PostgreSQL, миграции, сид данных, backend + интерфейс на :8000
```

Флаги `install.sh`: `--profile lite|demo|stress` (1 000 / 5 000 / 20 000 клиентов), `--reset` (снести данные и засеять заново), `--seed N` (воспроизводимая генерация), `--offline` (принудительно mock, без обращений в сеть), `--with-mailpit` (просмотр писем клиентам на :8025), `--with-tgbot` (поднять Telegram-бота — нужен токен).

После установки скрипт печатает адрес: интерфейс `http://<хост>:8000`, API `/api/health`, документация `/docs`. Если на ноутбуке есть `qrcode` для Python — покажет QR для телефона жюри.

Подсказка: если порт 8000 занят, поменяйте `APP_PORT` в `.env` и перезапустите `docker compose up -d`.

## 3. Файл `.env` — единственное место для секретов

`.env` лежит в корне, создаётся из `.env.example`, **в git не попадает** (`.gitignore`), в образ не копируется (`.dockerignore`), читается контейнером backend при старте. Никогда не вписывайте ключи в `docker-compose.yml`, `README`, карточки задач или чат.

```ini
APP_ENV=dev                 # prod отключает /docs и включает строгие проверки
APP_SECRET=…                # install.sh генерирует сам; менять не нужно
APP_PORT=8000
PROFILE=lite                # lite | demo | stress
SIM_SEED=42                 # одинаковый seed → одинаковые клиенты и история

DATABASE_URL=postgresql+psycopg://cx:cx@postgres:5432/cx_pulse   # внутри compose; локально — localhost

LLM_PROVIDER=mock           # основной провайдер: gigachat | openai_compat | replay | mock
LLM_CHAIN=gigachat,openai_compat,replay,mock   # порядок отказоустойчивости: нет ключа/ошибка → следующий
LLM_RECORD=false            # true — записывать ответы живой модели в data/cassettes (replay без сети)

GIGACHAT_AUTH_KEY_1=        # Authorization key (base64 «client_id:secret»), НЕ access token
GIGACHAT_AUTH_KEY_2=        # второй ключ — ротация при лимитах, можно пусто
GIGACHAT_SCOPE=GIGACHAT_API_PERS   # PERS для физлица, CORP/B2B для юрлица
GIGACHAT_BASE_URL=https://api.giga.chat/v1
GIGACHAT_OAUTH_URL=https://ngw.devices.sberbank.ru:9443/api/v2/oauth
GIGACHAT_MODEL=GigaChat-3-Pro      # отвечает агент; id из GET https://api.giga.chat/v1/models: GigaChat-3-Pro, GigaChat-3-Ultra, GigaChat-3-Lightning
GIGACHAT_VERIFY_SSL=false   # true только если в контейнер добавлен сертификат Минцифры

OPENROUTER_API_KEY=         # альтернатива GigaChat (OpenAI-совместимый API)
LOCAL_LLM_BASE_URL=         # локальная модель (Ollama/vLLM), например http://host.docker.internal:11434/v1

TELEGRAM_BOT_TOKEN=         # только если нужен бот; иначе пусто
MAILPIT_ENABLED=false
STT_PROVIDER=none           # vosk | browser | none — распознавание речи для отделений (пакет B10)
```

### Как безопасно передать ключи

- Передавайте ключ человеку, который ставит стенд, через менеджер паролей или одноразовую ссылку (например, Bitwarden Send / корпоративный аналог), не в мессенджере в открытом виде. После демо ключ отзовите в кабинете провайдера.
- На сервере: `nano .env` → вписать значения → `docker compose up -d backend` (контейнер перечитает `.env`). Права на файл: `chmod 600 .env`.
- Проверка, что ключ подхватился: `curl -s localhost:8000/api/health` — в блоке `llm` у профиля `gigachat_*` должно быть `ok`; в логах `docker compose logs backend | grep gigachat_token` появится строка о получении токена. Если ключа нет, backend пишет `llm_chain_skip … нет GIGACHAT_AUTH_KEY_*` и работает на mock — это штатно.
- Ключи никогда не пишутся в логи и в БД: провайдер логирует только метку ключа (`gigachat_env_1`) и срок жизни токена.
- Мастер настройки в интерфейсе (`/setup`, ввод ключа через форму с проверкой «Тест подключения») описан в OpenAPI, реализация — карточка T-010; до него единственный способ — `.env`.

### Режимы модели

| Режим | Когда | Что происходит |
|---|---|---|
| `mock` | без сети, репетиции, автотесты | детерминированная классификация по ключевым словам, ответы по шаблонам |
| `replay` | демо без интернета после репетиции с живой моделью | ответы из кассет `data/cassettes`, записанных при `LLM_RECORD=true` |
| `gigachat` | показ с живой моделью | OAuth по Authorization key, лимиты и ротация ключей, при сбое — автоматический откат на `replay`/`mock` |

Список моделей берите с `https://api.giga.chat/v1/models` (тот же хост, что у SDK `base_url`). Там есть `GigaChat-3-Ultra`, `GigaChat-3-Pro` и `GigaChat-3-Lightning`. Старый хост `gigachat.devices.sberbank.ru` этих id не отдаёт и отвечает 404.

Рекомендация на демо: накануне прогнать сценарии с живой моделью при `LLM_RECORD=true`, на показе оставить `LLM_CHAIN=gigachat,replay,mock` — при проблемах с сетью зрители не заметят переключения.

## 4. Проверка после установки

```bash
curl -s localhost:8000/api/health | python3 -m json.tool   # db: true, sim_running, llm: {...}
make scenario ID=2                                          # прогон демо-сценария 2 с проверкой ожиданий
make scenario                                               # все 9 запускаемых сценариев (3–5 минут)
```

Откройте `http://<хост>:8000`: в шапке — сим-часы и кнопка «Старт», в KPI-полосе — счётчики, во вкладке «Сигналы» — история последних 14 сим-дней.

## 4а. Мастер настройки в интерфейсе

Откройте `http://<хост>:8000/setup` (пункт «Настройки» в шапке). Девять шагов, каждый сохраняется отдельно, порядок свободный:

1. **LLM** — какие профили основной / быстрый / двойник; «Проверить» делает реальный запрос к модели. Блок «Ключи и цепочка провайдеров (.env)» записывает `GIGACHAT_AUTH_KEY_*`, `OPENROUTER_API_KEY`, `LLM_CHAIN`, `LLM_PROVIDER` и т. д. прямо в `.env` и сразу пересобирает цепочку агента — перезапуск не нужен. Секреты наружу не возвращаются (виден только хвост).
2. **Банк и клиенты** — название банка, профиль базы (lite / demo / stress), регионы, доли сегментов.
3. **Эмуляция** — seed и интенсивности событий (только при остановленной эмуляции); блок «.env»: `PROFILE`, `SIM_SEED` (нужен перезапуск).
4. **Каналы** — включённые каналы, проверка токена Telegram-бота (getMe); блок «.env»: `TELEGRAM_BOT_TOKEN`, `MAILPIT_ENABLED`, `STT_PROVIDER`, `STT_MODEL_PATH`; таблица провайдеров распознавания с кнопкой «Проверить» (WER по тестовому файлу).
5. **Политики агента** — порог уверенности, окно дедупликации, правила HITL/эскалации. Читаются агентом при каждом запуске.
6. **SLA и маршрутизация** — матрица 3×3 и правила маршрутизации в команды.
7. **Экономика** — параметры формулы dCLTV, коэффициенты удержания, ставки доходности.
8. **Шаблоны и двойники** — тексты уведомлений, каталог подарков, доли психотипов.
9. **Данные и запуск** — генерация базы (идемпотентна; «Сбросить историю» удаляет клиентов и историю), матрица покрытия, «Завершить настройку».

Кнопки «Экспорт» / «Импорт» переносят все настройки одним JSON (без секретов) между стендами.

Как мастер правит `.env`: файл перезаписывается на месте с сохранением порядка и комментариев (в Docker он смонтирован как `/data/env/.env`, переменная `ENV_FILE`), значения применяются к работающему процессу; `GET /api/settings/env` показывает путь, источник каждого значения (файл / окружение / значение по умолчанию) и маски секретов.

### Распознавание речи (микрофон)

```bash
make stt-model      # скачать vosk-model-small-ru-0.22 (≈45 МБ) в data/models/stt — работает офлайн, в Docker подхватывается через том ./data
```

Без модели доступен провайдер «Браузер» (Web Speech API в Chrome/Edge — речь уходит сервису браузера). Доступ к микрофону браузер даёт только на `localhost` или по HTTPS.

## 5. Обновление, перезапуск, сброс

```bash
git pull && docker compose build && docker compose up -d   # обновить код
docker compose restart backend                             # перечитать .env
./install.sh --reset --profile lite                        # снести данные, засеять заново (ключи в .env сохраняются)
docker compose down -v                                     # полное удаление вместе с БД
```

Логи: `docker compose logs -f backend` (структурированные JSON-строки; поиск по `event=`). Бэкап БД: `docker compose exec postgres pg_dump -U cx cx_pulse > backup.sql`.

## 6. Установка без Docker (разработка)

```bash
make install-backend && make migrate && make seed PROFILE=lite   # нужна локальная PostgreSQL 16+ и DATABASE_URL в .env
make dev                        # backend :8000 на mock
make install-front && make dev-front                            # vite :5173, прокси /api и /ws → :8000
make build-front                # собрать фронт; backend отдаёт его сам на :8000
make test                       # контракты, unit, интеграционные и сценарные тесты (DATABASE_URL_TEST)
make e2e                        # дымовые Playwright-тесты против стенда (E2E_BASE_URL)
```

## 7. Частые проблемы

| Симптом | Причина и решение |
|---|---|
| `backend не поднялся за 120 с` | PostgreSQL ещё стартует или занят порт 5432 — `docker compose logs postgres`, повторить `install.sh` |
| В `health` у `gigachat_*` статус `error` | неверный ключ, не тот `GIGACHAT_SCOPE` или блокировка SSL — проверьте `GIGACHAT_VERIFY_SSL=false` для демо |
| Все обращения уходят в «Требует решения» | у клиентов накоплены повторы (3+) или сработали политики — это ожидаемо для Ultra VIP, регуляторных и мошеннических тем; проверьте `/engine` → шаг «Решение» → «Проверки политик» |
| Интерфейс открывается, но данных нет | симуляция на паузе — нажмите «Старт» в шапке; или сид не прошёл: `docker compose exec backend python /scripts/seed/run.py --profile lite` |
| Нет сим-времени/часы стоят | после перезапуска контейнера часы на паузе — «Продолжить» |
