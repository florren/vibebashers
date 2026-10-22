# CX Pulse Control

Демо-стенд ИИ-агента банковского клиентского опыта (CX) для хакатона «Синапс»: эмулятор банка генерирует операции, сбои и обращения клиентов; агент классифицирует сигналы, собирает контекст, принимает решение, при сомнении спрашивает человека (HITL), заводит инциденты и уведомления; отдельный контур проверяет транскрипты встреч и звонков на мисселлинг, грубость и неверные факты. Всё работает без внешних ключей на встроенной mock-модели; с ключами GigaChat / OpenRouter / локальной модели — на настоящей LLM.

Что внутри одним взглядом: `/` — рабочее место (лента сигналов, очередь HITL, инциденты), `/engine` — «под капотом» (шаги агента, граф, цепочка решений, живые события, вкладка «Качество»), `/compliance` — транскрипты и отчёты комплаенса, `/manager` — алерты руководителю отделения. Продуктовое описание — `docs/ONE-PAGER.md`, руководство пользователя — `docs/USER-GUIDE.md`.

---

## Содержание

- [Часть 1. Готовое приложение: скачать, настроить, запустить, показать](#часть-1-готовое-приложение-скачать-настроить-запустить-показать)
- [Часть 2. Руководство для тех, кто ведёт разработку ИИ-агентами](#часть-2-руководство-для-тех-кто-ведёт-разработку-ии-агентами)
- [Часть 3. Технические требования к устройству](#часть-3-технические-требования-к-устройству)
- [Часть 4. Технологии «в чистом виде»](#часть-4-технологии-в-чистом-виде)
- [Часть 5. Собственные решения: что, почему, что делает](#часть-5-собственные-решения-что-почему-что-делает)
- [Карта документации](#карта-документации)

---

## Часть 1. Готовое приложение: скачать, настроить, запустить, показать

### 1.1. Что понадобится

Два пути запуска:

| Путь | Когда выбирать | Что ставить |
|---|---|---|
| **Docker (рекомендуется для демо)** | ноутбук для показа, минимум ручных действий | Docker Desktop (Windows/macOS) или Docker Engine + Compose v2 (Linux), Git |
| **Нативно (для разработки)** | нужен hot-reload, отладка, тесты | PostgreSQL 16, Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 22, Git |

Проверка перед стартом: `docker --version` и `docker compose version` (нужен Compose v2), `git --version`. Требования к железу — в [части 3](#часть-3-технические-требования-к-устройству).

### 1.2. Скачать

```bash
# вариант А: git (нужен доступ к репозиторию)
git clone https://github.com/florren/vibebashers.git
cd vibebashers

# вариант Б: без git — на странице репозитория Code → Download ZIP, распаковать, открыть терминал в папке
```

Зеркало в GitVerse обновляется автоматически после каждого слияния в `main` (`.github/workflows/mirror.yml`) — если GitHub недоступен, клонируйте оттуда.

### 1.3. Настроить `.env` (ключи — безопасно)

1. Скопируйте шаблон: `cp .env.example .env` (Windows PowerShell: `Copy-Item .env.example .env`).
2. Откройте `.env` в редакторе. Для демо без интернета **ничего менять не нужно** — приложение работает на mock-модели.
3. Если есть ключ GigaChat: вставьте в `GIGACHAT_AUTH_KEY_1=` значение **Authorization key** из личного кабинета (длинная base64-строка; это не access token), проверьте `GIGACHAT_SCOPE` (`GIGACHAT_API_PERS` для физлица, `GIGACHAT_API_CORP`/`B2B` для юрлица). Второй ключ в `GIGACHAT_AUTH_KEY_2` — ротация при лимитах.
4. Альтернатива — `OPENROUTER_API_KEY=` (OpenAI-совместимый API) или локальная модель `LOCAL_LLM_BASE_URL=http://host.docker.internal:11434/v1` (Ollama/vLLM/LM Studio).
5. Порядок отказоустойчивости задаёт `LLM_CHAIN=gigachat,replay,mock`: нет ключа или ошибка — переход к следующему. Для показа «гарантированно без сети» поставьте `LLM_CHAIN=replay,mock` или запускайте `./install.sh --offline`.

Правила безопасности: `.env` лежит в корне, в git не попадает (`.gitignore`), в Docker-образ не копируется (`.dockerignore`). Ключи никогда не вписываются в `docker-compose.yml`, README, карточки задач, чат с агентом или промпт. Полный разбор переменных — `docs/SETUP.md`.

### 1.4. Запустить одной командой (Docker)

```bash
./install.sh                      # поднять PostgreSQL + backend (фронт собран внутрь), применить миграции, засеять данные (профиль lite)
./install.sh --profile demo       # 5 000 клиентов вместо 1 000 (для показа «живой» ленты)
./install.sh --offline            # принудительно mock, ни одного обращения в сеть
./install.sh --reset --seed 42    # снести данные и засеять заново воспроизводимо
./install.sh --with-mailpit       # просмотр писем клиентам на http://localhost:8025
```

Windows: запускайте из Git Bash или WSL2; либо руками: `docker compose up -d --build`, затем `docker compose exec backend alembic upgrade head` и `docker compose exec backend python /scripts/seed/run.py --profile lite`.

После старта: приложение — **http://localhost:8000**, API-документация — http://localhost:8000/docs, проверка — `curl -s localhost:8000/api/health` (ожидается `"status":"ok"`, `"db":true`; у LLM-профилей `ok` или `skip` без ключа — это штатно).

### 1.5. Запустить нативно (без Docker)

```bash
# PostgreSQL 16 запущен локально, пользователь/база cx:cx@localhost:5432/cx_pulse (и cx_pulse_test для тестов)
cp .env.example .env
make install-backend    # uv sync → backend/.venv
make install-front      # npm ci во frontend
make migrate            # alembic upgrade head
make seed PROFILE=lite  # данные
make dev                # backend :8000 с автоперезагрузкой
make dev-front          # в другом терминале: vite :5173 → proxy на :8000
```

`make help` показывает все цели: `lint`, `test`, `test-scenarios`, `sync-contracts`, `scenario`, `report`, `e2e`, `import-transcripts`.

### 1.6. Провести демо

Подробный сценарий с репликами — `docs/DEMO-SCRIPT.md`. Короткая последовательность:

1. Открыть http://localhost:8000, нажать **Старт** в шапке (эмуляция идёт в сим-времени, скорость ×120 по умолчанию). Через 20–40 секунд в ленте появляются сигналы, агент разбирает их; часть уходит в очередь **HITL**.
2. В очереди HITL принять одно решение (одобрить / изменить / отклонить) — показать, что человек правит агента и это сохраняется.
3. Карточка инцидента: маршрутизация в команду, SLA, уведомления, цепочка решений.
4. `/engine`: шаги агента с промптами и ответами модели, граф, живые события по WebSocket.
5. Комплаенс: в терминале `make scenario ID=9` и `make scenario ID=10` (или кнопка «Импорт корпуса» на `/compliance`). На `/manager` появятся алерты «порог срабатываний» и «немедленный»; по ссылке «Транскрипт» — отчёт с факт-чеком ставки по тарифам и пропущенными этапами скрипта.
6. Вкладка **Качество** на `/engine` — индекс здоровья и список «что доработать»: показать, что система сама говорит, где она на заглушках и где человек поправлял агента.
7. Режим жюри (кнопка в шапке): ввести свой текст обращения — агент разберёт его на глазах.

Полезно перед показом: `make scenario ID=all` — прогон всех сценариев ТЗ с результатом OK/FAIL; `make report` — отчёт о качестве в `data/reports/latest.md`.

### 1.7. Остановить, обновить, сбросить

```bash
docker compose down                 # остановить, данные остаются в томе
docker compose down -v              # остановить и удалить данные
git pull && ./install.sh            # обновить до свежего main (миграции применятся)
./install.sh --reset                # пересеять данные
docker compose logs -f backend      # логи; структурированный журнал — backend/var/log/app.jsonl (docs/REPORTS.md)
```

### 1.8. Если что-то не так

| Симптом | Что сделать |
|---|---|
| `install.sh` падает на `docker compose` | Нужен Compose v2 (`docker compose`, не `docker-compose`); на Linux добавьте пользователя в группу `docker` |
| Порт 8000/5432 занят | В `.env` поменяйте `APP_PORT`/`DATABASE_URL`, либо остановите локальный PostgreSQL |
| `/api/health` → `"db": false` | PostgreSQL ещё стартует (подождите 10–20 с) или неверный `DATABASE_URL` (внутри compose хост `postgres`, нативно — `localhost`) |
| В логах `llm_chain_skip … нет GIGACHAT_AUTH_KEY_*` | Штатно: ключа нет, работает mock. Проверьте `.env`, если ключ должен быть |
| Ответы агента шаблонные, без «живого» текста | Работает mock; вкладка «Качество» покажет «% LLM-шагов на fallback». Добавьте ключ или `LOCAL_LLM_BASE_URL` |
| Лента пустая после «Старт» | Эмуляция на паузе или ночь по сим-времени (видно в шапке); увеличьте скорость или нажмите «Старт» ещё раз |
| GigaChat: ошибка SSL | `GIGACHAT_VERIFY_SSL=false` (по умолчанию) или добавьте сертификат Минцифры в контейнер |

---

## Часть 2. Руководство для тех, кто ведёт разработку ИИ-агентами

Репозиторий спроектирован так, чтобы задачи выполняли ИИ-агенты (Codex, Cursor, Claude Code, Perplexity Computer, DeepSeek и локальные модели), а человек ставил задачи, проверял результат и сливал PR. Ниже — как это устроено и что делать по шагам.

### 2.1. Как устроен репозиторий для агентов

| Что | Где | Зачем |
|---|---|---|
| Правила для агентов (единый источник) | `AGENTS.md` | стек, структура, железные правила, DoD, как менять контракты; читается Codex и Cursor автоматически |
| Указатели для других harness | `CLAUDE.md` (Claude Code), `.cursor/rules/` (Cursor) | отсылают к `AGENTS.md`, чтобы не дублировать правила |
| Техническое задание | `docs/TZ.md`, `docs/TZ-additional.md`, `docs/BRD.md`, `docs/BRD-merge-analysis.md` | что строим; карточки ссылаются на разделы ТЗ |
| Контракты — источник истины | `contracts/db/schema.sql`, `contracts/api/openapi.yaml`, `contracts/schemas/*.json`, `backend/alembic/` | код генерируется из них (`make sync-contracts`), CI проверяет дрейф |
| Карточки задач (151) | `docs/tasks/T-xxx-*.md`, индекс `docs/tasks/README.md` | одна карточка — одна ветка — один PR; в карточке цель, шаги, критерии приёмки, команды проверки, «Отчёт субагента» |
| Пакеты карточек на спринт | `docs/PLAN-14D.md` | B01…B21 — что делать по дням до демо |
| Слои и владельцы | `docs/TEAM-SPLIT.md`, `CODEOWNERS` | L1 базис, L2 симулятор, L3 агент, L4 фронт, L5 качество; CI проверяет, что PR не вышел за слой |
| Рабочий цикл одной командой | `scripts/cx.py`, `docs/WORKFLOW.md` | worktree + промпт + запуск агента + проверки + PR |
| Промпт-шаблон задачи | `scripts/prompts/task.md` | что получает агент на входе: карточка, AGENTS.md, ТЗ, контракты, команды проверки |
| CI | `.github/workflows/ci.yml` | jobs `contracts`, `db`, `tests` (обязательные), `owners` (информационный); `mirror.yml` — зеркало в GitVerse |
| Отчёт о качестве | `make report`, `GET /api/reports/quality`, `docs/REPORTS.md` | что сломалось, что работает не так, что доработать — читают и люди, и агенты |

### 2.2. Подготовка рабочего места (общая для любого агента)

1. Установите Git, Python 3.12, uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`), Node.js 22, Docker (для тестов хватит локальной PostgreSQL 16), GitHub CLI `gh`.
2. Авторизуйте `gh auth login` под учёткой с правом писать в репозиторий (владелец даёт доступ: Settings → Collaborators → Add people; роль Write).
3. Клонируйте в структуру, которую ждёт `cx`:
   ```bash
   mkdir -p ~/dev && cd ~/dev
   git clone https://github.com/florren/vibebashers.git
   cd vibebashers && python scripts/cx.py doctor     # проверит git, gh, codex, uv, node
   alias cx='python ~/dev/vibebashers/scripts/cx.py'  # добавьте в ~/.bashrc
   ```
4. Поднимите БД для тестов: `docker compose up -d postgres`, в `.env` укажите `DATABASE_URL_TEST`. Проверьте `make lint && make test` на `main` — должны быть зелёные.
5. Настройте git-автора агента (`git config user.name/user.email`) — так в истории видно, кто из агентов что делал.

### 2.3. Codex (OpenAI Codex CLI)

1. `npm i -g @openai/codex`, затем `codex login` (ChatGPT-аккаунт или `OPENAI_API_KEY`).
2. В `~/.codex/config.toml` поднимите лимит чтения инструкций — `AGENTS.md` больше 32 КиБ:
   ```toml
   project_doc_max_bytes = 200000
   model = "gpt-5-codex"          # или другая доступная модель
   approval_policy = "never"      # cx start сам передаёт -a never -s workspace-write
   ```
3. Запуск задачи без участия человека: `cx start B06 --agent codex` (или `cx start T-171`). Скрипт создаёт worktree `../wt/B06`, собирает промпт из карточки и запускает `codex exec`. Для диалогового режима — `--interactive`.
4. Codex читает `AGENTS.md` сам; итог работы агент записывает в `../wt/B06/.cx/report.md` — этот текст `cx pr` подставит в описание PR.

### 2.4. Cursor

1. Установите Cursor, войдите в аккаунт; в настройках включите «Rules for AI» — проект уже содержит `.cursor/rules/`.
2. `cx start B06 --agent cursor` — создаст worktree и откроет папку в Cursor (если команда `cursor` в PATH), промпт задачи сохранится в `../wt/B06/.cx/prompt.md`.
3. В Cursor откройте Agent (Composer), вставьте содержимое `prompt.md`, режим Agent с автозапуском команд. Cursor подхватывает `AGENTS.md` и `.cursor/rules/` автоматически.
4. Дальше как обычно: `cx check B06`, `cx pr B06`.

### 2.5. Claude Code

1. `npm i -g @anthropic-ai/claude-code`, `claude` → вход в аккаунт Anthropic (или `ANTHROPIC_API_KEY`).
2. Claude Code читает `CLAUDE.md` в корне, который отсылает к `AGENTS.md`. Если хотите, добавьте в `~/.claude/settings.json` разрешения на `make`, `uv`, `npm`, `gh`, чтобы не подтверждать каждую команду.
3. Запуск: `cx start B06 --agent manual` (создаст worktree и промпт, агента не запустит), затем
   ```bash
   cd ../wt/B06 && claude -p "$(cat .cx/prompt.md)" --permission-mode acceptEdits
   ```
   или интерактивно: `claude`, затем вставить промпт.

### 2.6. DeepSeek, другие API-модели и локальные модели

Любая OpenAI-совместимая модель подключается через те же CLI-агенты:

- **Codex CLI с другим провайдером** — в `~/.codex/config.toml`:
  ```toml
  model_provider = "deepseek"
  model = "deepseek-chat"
  [model_providers.deepseek]
  name = "DeepSeek"
  base_url = "https://api.deepseek.com/v1"
  env_key = "DEEPSEEK_API_KEY"
  ```
  Для локальной модели: `base_url = "http://localhost:11434/v1"` (Ollama), `env_key` любой непустой. Дальше `cx start … --agent codex` работает без изменений.
- **Другие агентные CLI** (aider, opencode, Cline в VS Code) — укажите им модель и базовый URL по их документации и запускайте в worktree с промптом из `.cx/prompt.md` (`cx start … --agent manual`).
- **Локальные модели (Ollama / vLLM / LM Studio)** — честное ограничение: для этого репозитория (150+ файлов, строгие контракты, mypy strict) модели до ~30B часто не доводят задачу до зелёных проверок. Практика, которая работает: локальная модель — для маленьких карточек (S) и правок по логу `cx fix`, облачная — для пакетов B-уровня. Ограничьте контекст одной карточкой и запускайте `cx check` чаще.
- Модель **самого приложения** (не агента-разработчика) настраивается отдельно, в `.env` (`LLM_CHAIN`, `LOCAL_LLM_BASE_URL`) — см. часть 1.

### 2.7. Как подключить агента к репозиторию

1. **Доступ.** Владелец репозитория добавляет учётку агента (или человека, под чьим `gh` он работает) с ролью Write. Для API-токенов — fine-grained PAT с правами Contents: Read/Write, Pull requests: Read/Write, Actions: Read на один репозиторий; срок — не больше спринта.
2. **Ветки.** Агент никогда не пишет в `main` напрямую: ruleset требует PR и зелёные `contracts`, `db`, `tests`. Ветки `feat/<id>-…` создаёт `cx start`.
3. **Слои.** Карточка привязана к слою; `python scripts/check_owners.py --base main` (его вызывает `cx check`) падает, если агент тронул чужие файлы. Если это осознанно — PR получает метку `cross-layer` (и `contract-change`, если менялись контракты), сливает владелец L1.
4. **Секреты.** В промпт и в репозиторий ключи не попадают: `.env` в `.gitignore`, в карточках — только имена переменных. CI-секреты (`GITVERSE_TOKEN`) — в Settings → Secrets.
5. **Что агент должен прочитать перед задачей** (это уже зашито в `scripts/prompts/task.md`): `AGENTS.md` целиком, карточку, разделы ТЗ из карточки, контракты из карточки, `docs/REPORTS.md` при починках.

### 2.8. Как быстро узнать, что планировалось

1. `docs/ONE-PAGER.md` — зачем продукт (5 минут). `docs/BRD.md` — бизнес-требования, `docs/TZ.md` + `docs/TZ-additional.md` — техническое задание (разделы нумерованы, карточки на них ссылаются).
2. `docs/tasks/README.md` — все 151 карточка по **волнам** (порядок) и по **слоям** (кто ведёт), с оценкой и признаком «в демо-минимуме».
3. `docs/PLAN-14D.md` — какие карточки собраны в пакеты B01…B21 и на какой день; раздел 4 — что сознательно отрезано до демо.
4. Конкретная карточка `docs/tasks/T-xxx-*.md`: цель, разделы ТЗ, контракты, шаги, критерии приёмки, команды проверки, зависимости.
5. Контракт как план: все эндпоинты есть в `contracts/api/openapi.yaml` ещё до реализации — нереализованные отвечают 501 с номером карточки.

### 2.9. Как узнать, что сделано, а что нет

| Вопрос | Команда / место |
|---|---|
| Статус карточек | `grep -l 'Статус | \`done\`' docs/tasks/T-*.md \| wc -l` (аналогично `todo`, `in_progress`); в индексе `docs/tasks/README.md` статус в таблицах. Сейчас: 58 done, 6 in_progress, 87 todo |
| Что именно сделано по карточке | раздел «Отчёт субагента» в конце карточки: ветка/PR, что сделано, отклонения, затронутые контракты |
| Какие функции ещё заглушки | `grep -rn "NotImplementedYet(" backend/app/api \| sed 's/.*NotImplementedYet(//' \| sort \| uniq -c \| sort -rn` — список карточек с числом эндпоинтов-заглушек; на стенде такой эндпоинт отвечает 501 и полем `card` |
| Что из проверок сценариев ТЗ ещё не реализовано | `NOT_YET` в `backend/app/sim/scenarios.py`; `make scenario ID=all` — OK/FAIL по каждому сценарию |
| Где система «работает, но не так» | `make report` или вкладка «Качество» на `/engine`: правки HITL, fallback на правила, ложные алерты, 501-вызовы (спрос на нереализованное), ошибки |
| История | `docs/CHANGELOG.md`, `git log --oneline`, `gh pr list --state merged` |
| Что в работе прямо сейчас | `cx status` — worktree, ветки, PR и состояние CI |

### 2.10. Как сделать задачу (пошагово)

1. `cx next` — подскажет пакет на сегодня из `PLAN-14D` или карточку без незакрытых зависимостей. Либо выберите сами в `docs/tasks/README.md`.
2. `cx start <B06|T-171> --agent codex|cursor|manual` — worktree, окружение, промпт, запуск агента.
3. Дождитесь завершения (Codex пишет итоговый отчёт в `../wt/<id>/.cx/report.md`; промпт — там же в `prompt.md`). Агент обязан заполнить «Отчёт субагента» в карточке и поставить статус.
4. `cx check <id>` — contracts, owners, lint, test; лог в `.cx/check.log`. Красное → `cx fix <id>` (агент получает лог и чинит), конфликт с `main` → `cx fix <id> --rebase`.
5. `cx pr <id>` — коммит остатков, rebase, push, PR с отчётом агента в описании. CI запускается сам.
6. Проверьте PR глазами: описание, скриншоты/логи из отчёта, нет ли секретов и лишних файлов; при `contract-change` — что обновлены `schema.sql` + alembic + OpenAPI + JSON-схемы + TS-типы.
7. Слияние: Squash and merge (ruleset требует зелёные `contracts`, `db`, `tests`; `owners` и `mirror` для PR с меткой `cross-layer` могут быть красными — это информационно). После слияния `cx done <id>`.
8. При желании — `make report` до и после: индекс здоровья и рекомендации должны измениться в лучшую сторону.

### 2.11. Как доделать задачу, которую начал другой и не закончил

1. Найдите следы: `cx status` (worktree/ветки на этой машине), `gh pr list --state open` и `git branch -r | grep <id>` (ветки на GitHub), карточка со статусом `in_progress` и частично заполненным «Отчётом субагента».
2. Прочитайте отчёт субагента и диффы: `gh pr diff <номер>` или `git log origin/main..origin/feat/<id>-… --stat`. Поймите, какие пункты «Шаги» карточки закрыты, какие нет.
3. Если ветка существует удалённо: `cx start <id>` на той же машине продолжит существующий worktree; на другой машине — `git fetch && git worktree add ../wt/<id> feat/<id>-…` и затем `cx start <id> --agent …` (скрипт увидит worktree и не будет создавать заново).
4. Дополните промпт: в `../wt/<id>/.cx/prompt.md` допишите блок «Что уже сделано предыдущим исполнителем … Что осталось …» (возьмите из отчёта и диффа) и запустите агента (`--interactive` для Codex или вручную для Cursor/Claude).
5. Если чужая ветка безнадёжно устарела или сломана: `cx done <id> --force` (удалит worktree и локальную ветку), удалите удалённую ветку, закройте PR с комментарием, перенесите полезные куски руками через `git cherry-pick` и начните `cx start <id>` заново.
6. Дальше по общему циклу: `cx check` → `cx pr` → слияние → `cx done`. В «Отчёте субагента» укажите обоих исполнителей и что изменилось.

### 2.12. Как запросить новый функционал

1. Сформулируйте требование на языке ТЗ: пользователь, путь, ожидаемый результат, что видно на экране/в API. Если это изменение требований — допишите раздел в `docs/TZ-additional.md` (PR в L1).
2. Заведите карточку: карточки генерируются скриптом — добавьте запись `dict(id=223, title=…, epic=…, agent=…, size=…, wave=…, goal=…, tz=[…], contracts=[…], deps=[…], steps=[…], accept=[…], check=[…])` в список в `scripts/gen_tasks.py` и выполните `python scripts/gen_tasks.py` — появится `docs/tasks/T-223-*.md` и обновится индекс. Пример свежей карточки — `T-222`.
3. Если нужен новый эндпоинт/таблица/событие — сначала контракт: `contracts/api/openapi.yaml`, `contracts/db/schema.sql` + миграция alembic, JSON-схема; затем `make sync-contracts`. Эндпоинт можно оставить заглушкой 501 с номером карточки — так спрос на него станет виден в отчёте о качестве.
4. При необходимости добавьте карточку в пакет в `docs/PLAN-14D.md` и запустите цикл из 2.10.
5. Быстрый путь без карточки (мелочь на час): `cx start T-xxx --agent codex --interactive` для ближайшей по смыслу карточки и опишите задачу в диалоге; но результат всё равно оформляется через `cx pr`.

### 2.13. Как это проверяет CI и когда просить человека

- `contracts`: `scripts/contracts_check.py` (JSON-схемы и OpenAPI валидны, примеры проходят), дрейф OpenAPI ↔ код (`scripts/check_openapi_drift.py`), i18n (`scripts/i18n_check.py`).
- `db`: `alembic upgrade head`, `alembic check`, схема совпадает с `contracts/db/schema.sql`.
- `tests`: ruff, ruff format, mypy strict, pytest (unit, integration, scenarios) на PostgreSQL в сервисе CI; фронт: eslint, tsc, vitest, build, проверка сгенерированных TS-типов.
- `owners`: границы слоя (информационный для `cross-layer`).
- Человек нужен для: слияния PR с метками `contract-change`/`cross-layer`, изменений ТЗ, ключей и доступа, решения «режем или переносим» по `docs/PLAN-14D.md` §5.

---

## Часть 3. Технические требования к устройству

| Сценарий | CPU | RAM | Диск | ОС / ПО | Примечание |
|---|---|---|---|---|---|
| **Демо на ноутбуке (Docker, mock или облачная LLM)** | 4 ядра x86-64 или Apple Silicon | 8 ГБ (Docker Desktop выделить ≥ 4 ГБ) | 5 ГБ свободно (образы ~1,5 ГБ + том БД ≤ 1 ГБ на профиле demo) | Windows 10/11 + WSL2, macOS 13+, Ubuntu 22.04+; Docker Desktop / Engine + Compose v2; браузер Chrome/Edge/Firefox актуальной версии, разрешение от 1366×768 (рабочее место рассчитано на 1440×900+) | интернет нужен только для GigaChat/OpenRouter; `--offline` — полностью автономно |
| **Профиль stress (20 000 клиентов)** | 8 ядер | 16 ГБ | 10 ГБ | то же | PostgreSQL в compose запущен с `shared_buffers=256MB`, `max_connections=200`; при stress поднимите до 1 ГБ |
| **Разработка нативно + тесты** | 4–8 ядер | 16 ГБ | 10 ГБ | PostgreSQL 16, Python 3.12, uv, Node.js 22, Git, gh; Playwright для e2e (`npx playwright install chromium`) | полный `make test` ≈ 1 мин, фронт-сборка ≈ 10 с |
| **Локальная LLM для приложения или для агента-разработчика** | 8+ ядер | 32 ГБ; GPU 12–24 ГБ VRAM (модели 7–14B в q4–q8) | +10–40 ГБ под веса | Ollama / vLLM / LM Studio с OpenAI-совместимым API | в `.env`: `LOCAL_LLM_BASE_URL`; латентность узлов агента вырастет до секунд, лимиты `fast_path` 8 с / `detector` 2 с в `app/llm/failover.py` |
| **Сервер для командного стенда** | 4 vCPU | 8 ГБ | 20 ГБ SSD | Linux, Docker; обратный прокси (nginx/Caddy) с TLS, если доступ извне | один процесс backend обслуживает WS и фон эмуляции; горизонтальное масштабирование не предусмотрено (демо) |

Сеть и порты: 8000 (приложение и API), 5432 (PostgreSQL, можно не публиковать), 8025/1025 (Mailpit, опционально), 5173 (Vite в режиме разработки). Исходящие: `ngw.devices.sberbank.ru:9443` и `gigachat.devices.sberbank.ru` для GigaChat, `openrouter.ai` для OpenRouter, `api.telegram.org` для бота.

---

## Часть 4. Технологии «в чистом виде»

То, что взято как есть и может использоваться для собственных решений.

| Слой | Технология | Версия | Роль в проекте |
|---|---|---|---|
| Язык backend | Python | 3.12 | весь backend, скрипты, сид, генераторы |
| Web-фреймворк | FastAPI + Uvicorn | ≥ 0.115 | REST (OpenAPI), WebSocket `/ws/stream`, раздача собранного SPA |
| Валидация и настройки | Pydantic v2, pydantic-settings | ≥ 2.9 | модели API (генерируются из JSON-схем), `.env` |
| БД | PostgreSQL | 16 | единственное хранилище: данные, события, LLM-кассеты, состояние эмуляции; `LISTEN/NOTIFY` как шина |
| Доступ к БД | psycopg 3 (async, pool), SQLAlchemy 2 (модели), Alembic | ≥ 3.2 / 2.0 / 1.13 | сырые SQL в горячих путях, ORM-модели для сида/тестов, миграции 0001–0003 |
| Логи | structlog | ≥ 24 | структурированные события; JSON в prod, консоль в dev |
| HTTP-клиент | httpx | ≥ 0.27 | GigaChat, OpenAI-совместимые API, скрипты |
| Схемы и сериализация | jsonschema, orjson, PyYAML | — | валидация событий и ответов LLM по контрактам, быстрый JSON, справочники в YAML |
| Качество кода | ruff (lint + format), mypy strict, pytest + pytest-asyncio | — | единые проверки локально (`make lint`, `make test`) и в CI |
| Пакеты Python | uv | — | lock-файл, `uv sync`, воспроизводимые окружения |
| Генерация кода | datamodel-code-generator, sqlacodegen, openapi-typescript | — | Pydantic из JSON-схем, SQLAlchemy из БД, TS-типы из OpenAPI |
| Язык frontend | TypeScript (strict) | 5.6 | весь фронт |
| UI | React 18, react-router-dom 6, TanStack Query 5, zustand 5 | — | SPA, маршруты, кэш данных с инвалидацией по WS, лёгкое состояние |
| Стили | Tailwind CSS 3, шрифты Inter / JetBrains Mono | — | дизайн-токены в `tailwind.config.ts`, светлая/тёмная тема |
| Локализация | i18next, react-i18next | — | все строки в `src/shared/i18n/ru.json`, проверка покрытия enum-ов |
| Иконки, даты | lucide-react, date-fns | — | — |
| Сборка и тесты фронта | Vite 5, Vitest 2, Testing Library, ESLint 9, Playwright | — | сборка в `backend` образ, unit-тесты, e2e-дым |
| Контейнеры | Docker, Docker Compose v2, образы `python:3.12-slim`, `node:22-alpine`, `postgres:16`, `axllent/mailpit` | — | один `install.sh` поднимает стенд |
| CI/CD | GitHub Actions, GitHub rulesets, CODEOWNERS; зеркало GitVerse | — | обязательные проверки `contracts`/`db`/`tests` |
| LLM-провайдеры | GigaChat API (OAuth по Authorization key), OpenRouter / любой OpenAI-совместимый API (`/v1/chat/completions`), Ollama / vLLM / LM Studio | — | подключаются через один интерфейс `app/llm/base.py` |
| Инструменты агентов-разработчиков | OpenAI Codex CLI, Cursor, Claude Code, GitHub CLI `gh`, git worktree | — | см. часть 2 |

Чего **нет** намеренно: LangGraph/LangChain (собственный лёгкий раннер графа), Redis/Kafka (шина — PostgreSQL `LISTEN/NOTIFY`), Celery (фоновые задачи — `asyncio` в процессе), ORM в горячих путях (сырой SQL через psycopg), внешние трекеры задач (карточки в репозитории).

---

## Часть 5. Собственные решения: что, почему, что делает

| Решение | Почему так | Что делает |
|---|---|---|
| **Контракты первичны, код генерируется** (`contracts/` → `make sync-contracts`; `scripts/gen_enums.py`, `gen_models.py`, `gen_schemas.py`, `gen_api_stubs.py`, `check_openapi_drift.py`) | несколько агентов параллельно меняют слои; без единого источника истины фронт и бэк расходятся за день | enums, Pydantic-модели, SQLAlchemy-модели, TS-типы и роутеры создаются из DDL/OpenAPI/JSON-схем; CI падает при расхождении спецификации и кода (сейчас 159 операций = 159) |
| **Заглушки 501 с номером карточки** (`app/errors.py::NotImplementedYet`) | весь API виден с первого дня; фронт пишется против контракта, не дожидаясь бэка | каждый нереализованный эндпоинт отвечает `application/problem+json` с полем `card: T-xxx`; отчёт о качестве считает вызовы 501 как «спрос на нереализованное» |
| **Карточки задач как код** (`scripts/gen_tasks.py` → `docs/tasks/*.md` + индекс по волнам и слоям) | у агента должен быть законченный, самодостаточный вход; статусы и зависимости нужно считать скриптом | 151 карточка с целью, разделами ТЗ, контрактами, шагами, критериями приёмки, командами проверки, зависимостями и «Отчётом субагента»; статусы сохраняются при регенерации |
| **`cx.py` — рабочий цикл одной командой** (`docs/WORKFLOW.md`) | руководитель без опыта разработки не должен помнить worktree, флаги Codex и `gh` | `next / start / check / fix / pr / done / status / clean / doctor`: worktree на карточку, промпт из шаблона, запуск Codex/Cursor, проверки с логом, PR с отчётом агента, уборка после слияния |
| **Слои и `check_owners.py`** (`CODEOWNERS`, `docs/TEAM-SPLIT.md`) | параллельные агенты не должны переписывать чужие файлы | PR проверяется на выход за слой карточки; осознанные исключения — метки `cross-layer` / `contract-change`, сливает владелец L1 |
| **Единый интерфейс LLM + цепочка отказоустойчивости** (`app/llm/base.py`, `failover.py`, `keys.py`, `ratelimit.py`) | демо не должно зависеть от доступности и квот одного провайдера | `ProviderChain`: таймауты по контексту (`fast_path` 8 с, `detector` 2 с, `default` 30 с), любая ошибка → следующий провайдер; пул ключей GigaChat с ротацией, rate limiter, учёт токенов в `agent_steps` |
| **Mock-модель на правилах, заполняющая любую схему** (`app/llm/mock.py`) | стенд обязан работать без ключей и сети, детерминированно для тестов | эвристики по ключевым словам (тип сигнала, тональность, флаги), генерация валидного объекта под любую JSON-схему; блок-подсказка `<<mock_verdict>>` позволяет узлам передать правило-вердикт, чтобы mock повторял логику правил |
| **Replay-кассеты** (`app/replay/store.py`, `data/cassettes/*.jsonl`, таблица `llm_cassettes`) | воспроизводимое демо и тесты «как с настоящей моделью», но без сети | ответы модели кэшируются по `sha256(provider, model, messages, schema)`; провайдер `replay` в цепочке отдаёт записанное |
| **Собственный раннер графа агента вместо LangGraph** (`app/agent/graph.py`, `nodes.py`, `runner.py`) | меньше зависимостей, чекпоинт и трассировка должны лежать в нашей БД и быть видны в UI | узлы `ingest → normalize → identify_client → gather_context → classify → check_rules → decide → wait_human → act → close`; каждый шаг — строка `agent_steps` с промптом, ответом, латентностью, токенами и статусом `ok/retry/fallback/error`; пауза на HITL и возобновление по `thread_id` |
| **Политики HITL и правила как данные** (`app/agent/policies.py`, `data/*.yaml`, таблицы `hitl_policies`, `routing_rules`) | человек должен править поведение без кода; правки должны учиться | четыре ветки HITL (одобрить/изменить/отклонить/делегировать), `human_decisions` с `agent_proposal` и `modified_proposal`, флаг `use_as_fewshot`; маршрутизация и SLA — матрица из YAML |
| **Нормализатор входов** (`app/ingest/`) | сигналы приходят из эмулятора, REST, транскриптов, ленты — агент должен видеть один формат | все источники приводятся к `ingest/signal`-схеме с `origin`, `channel`, `tracking_token` |
| **Эмулятор банка в сим-времени с детерминированным RNG** (`app/sim/clock.py`, `rng.py`, `engine.py`, `generators.py`, `events.py`, `runs.py`) | 14 дней «жизни банка» за минуты, воспроизводимо по сиду, с изолированными запусками | `SimClock` с ускорением ×1…×300 и фазами дня, `random.Random` с сериализацией состояния в `sim_state`, шина событий, валидирующая каждое событие по JSON-схеме, запуски `sim_runs` (сравнение «до/после», сброс к сиду) |
| **Шина на `LISTEN/NOTIFY` → WebSocket-хаб** (`app/realtime/`) | без Redis/Kafka; одна БД — один источник правды для UI | `NotifyBridge` слушает каналы PostgreSQL, маршрутизирует в темы (`signals`, `hitl`, `incidents`, `compliance`, …), фронт инвалидирует кэш TanStack Query по теме |
| **Сид с профилями и матрицей покрытия** (`scripts/seed/`, `data/corpus/`, `data/bench/`) | данные должны покрывать все типы сигналов, психотипы, регионы и сценарии ТЗ | профили lite/demo/stress (1 000 / 5 000 / 20 000 клиентов), идемпотентный сид, корпуса текстов и золотые наборы бенчмарков |
| **Сценарии ТЗ как исполняемые проверки** (`data/scenarios/*.yaml`, `app/sim/scenarios.py`, `scripts/scenario_check.py`, `tests/scenarios/`) | «демо-сценарий» должен быть и автотестом, и кнопкой на стенде | один YAML описывает инъекцию (операция, сбой, пост, транскрипт) и ожидания (тип сигнала, команда, HITL, паттерны, алерты); результат хранится в `scenarios.last_result` и виден в отчёте о качестве |
| **Комплаенс: правила-гейт + LLM-подтверждение + факт-чек** (`app/compliance/`) | модель дорогая и ошибается; правила — дешёвые, но шумные; соединение даёт объяснимость | правила (ключевые фразы с нечётким совпадением, факт-чек ставок/комиссий по `products.tariffs` с числами словами, этапы скрипта с отрицаниями) дают предварительную находку → LLM подтверждает и объясняет (`misselling_detect`), счётчик → алерт `threshold`/`immediate` → инцидент и уведомление руководителю; отчёт `transcript_report` с цитатами, «сказано/по тарифам», планом действий |
| **Наблюдаемость и отчёт о качестве** (`app/observability/`, `docs/REPORTS.md`) | команда из агентов и людей должна понимать, где сломалось, где работает не так и что доработать, не читая stdout | JSONL-журнал с `request_id`, HTTP-счётчики по маршрутам, кольцевой буфер ошибок; отчёт по `agent_runs/agent_steps/human_decisions/incidents/scenarios/compliance` с правилами рекомендаций («где смотреть») и индексом здоровья; `make report`, `GET /api/reports/quality`, вкладка «Качество» |
| **SPA раздаётся backend-ом** (`backend/Dockerfile` многостадийный) | один контейнер, один порт, нет CORS на демо | фронт собирается `node:22-alpine` и копируется в образ Python; `/` → SPA, `/api`, `/ws`, `/docs` → FastAPI |
| **Все тексты UI через i18n с проверкой enum-ов** (`scripts/i18n_check.py`) | русский — язык продукта; коды из контрактов должны иметь перевод | CI падает, если для значения enum из `common.schema.json` нет строки в `ru.json` |

---

## Карта документации

- `AGENTS.md` — правила для агентов; `CLAUDE.md`, `.cursor/rules/` — указатели на них.
- `docs/SETUP.md` — настройка стенда и безопасная передача ключей; `docs/DEMO-SCRIPT.md` — сценарий демо; `docs/USER-GUIDE.md` — руководство пользователя; `docs/ONE-PAGER.md` — одностраничник о продукте.
- `docs/TZ.md`, `docs/TZ-additional.md`, `docs/BRD.md`, `docs/BRD-merge-analysis.md` — требования.
- `docs/tasks/README.md` — карточки задач по волнам и слоям; `docs/PLAN-14D.md` — спринт до демо; `docs/TEAM-SPLIT.md` — слои и роли; `docs/WORKFLOW.md` — рабочий цикл `scripts/cx.py`; `docs/REPO-BOOTSTRAP.md` — репозиторий, ruleset и CI.
- `docs/REPORTS.md` — журнал и отчёт о качестве (`make report`); `docs/CHANGELOG.md` — журнал изменений.
- `contracts/` — DDL, миграции, OpenAPI, JSON-схемы: источник истины.
