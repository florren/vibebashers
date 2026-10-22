# Репозиторий: как залить пакет, включить защиту `main` и проверить связку PR → CI → merge → зеркало

Состояние на 21.10.2026 (проверено через GitHub): `github.com/florren/vibebashers` — ветка `main` (protected), файлы `LICENSE`, `README.md`, `.github/workflows/mirror.yml`; зеркало в `gitverse.ru/florren/vibebashers` работает (прогоны `mirror-to-gitverse` зелёные). Пакет контрактов ещё не залит.

## 1. Что в пакете относится к репозиторию

| Файл | Назначение |
|---|---|
| `.github/workflows/ci.yml` | CI: job'ы `contracts`, `db`, `owners`, `tests`. Работает уже на пакете без кода приложения; карточка T-001 усиливает шаги, имена job'ов не меняет |
| `.github/workflows/mirror.yml` | уже в репозитории — пакет его **не содержит и не перезаписывает** |
| `.github/pull_request_template.md` | шаблон PR с чек-листом DoD |
| `CODEOWNERS` | владение каталогами по слоям; заменить `@layer-l1…l5` на логины GitHub (один участник — везде `@florren`) |
| `Makefile`, `scripts/` | цели `check-contracts`, `check-owners`, `tasks`; скрипты проверок, которые вызывает CI |

Что делает CI уже сейчас, без кода: проверяет JSON-схемы и OpenAPI, пересобирает карточки и сверяет с закоммиченными, парсит DDL; поднимает PostgreSQL 16 и применяет `schema.sql`, затем дважды миграции 0002 и 0003 (должны быть no-op), проверяет число таблиц и представления; в PR — границы слоя по CODEOWNERS. Всё это проверено локально на PostgreSQL 18 перед выпуском пакета: чистая схема v1.4, идемпотентность, пути обновления v1.2 → 0002 → 0003 и v1.3 → 0003, откат 0003 и повторный накат — 74 таблицы во всех случаях.

## 2. Порядок (ветка `main` уже защищена — порядок важен)

1. **Settings → Rules → Rulesets**: временно поставить Enforcement = Disabled (или оставить только Block force pushes / Restrict deletions). Иначе прямой пуш пакета не пройдёт, а PR с «Require status checks» зависнет в «Expected — waiting for status», потому что `ci.yml` ещё ни разу не запускался.
2. Распаковать архив пакета в корень клона так, чтобы `AGENTS.md`, `contracts/`, `docs/`, `.github/workflows/ci.yml` оказались в корне рядом с `LICENSE` и `README.md`. Существующий `mirror.yml` оставить. В `CODEOWNERS` проставить логины. `README.md` заменить содержательным (кратко: что это, как запустить, ссылки на `AGENTS.md`, `docs/TZ.md`, `docs/PLAN-14D.md`).
3. Один коммит в `main`: `chore: пакет документации и контрактов v1.4.2 + CI` — последний прямой пуш.
4. Actions → дождаться зелёного `ci` на `main` (job'ы `contracts`, `db`, `tests`; `owners` на push не запускается — это нормально) и зелёного `mirror-to-gitverse`. Проверить на GitVerse, что `main` обновился.
5. Включить ruleset для `main`: Require a pull request (approvals 0), Require status checks — `contracts`, `db`, `tests` (появятся в списке после шага 4), Require branches to be up to date, Block force pushes, Restrict deletions. `owners` в обязательные не включать: он выполняется только для PR и для PR с меткой `cross-layer` печатает список без падения.
6. Тестовый PR: ветка `chore/T-000-smoke`, правка в `README.md`, PR → все четыре job'а → merge → зеркало. Пока эта цепочка не пройдена, агентов по карточкам не запускать.

## 3. Секреты и лимиты

- `GV_USER`, `GV_TOKEN` для зеркала уже заданы (прогон зелёный). Если на GitVerse включат защиту `main`, `--force` упрётся — снять защиту на зеркале.
- Для CI секреты не нужны: LLM в тестах — `LLM_PROVIDER=mock`, кассеты `replay` в репозитории.
- GitHub Actions: приватный репозиторий — 2000 минут в месяц на бесплатном тарифе; четыре job'а на PR — около 6–10 минут; при 20–30 PR в неделю запас есть, но `concurrency` в `ci.yml` отменяет устаревшие прогоны одной ветки, чтобы не жечь минуты. Публичный репозиторий не лимитирован.

## 4. Как это стыкуется с рабочими местами

- Codex (локально или Cloud), Cursor и Perplexity Computer работают с GitHub: клон, ветка `feat/T-NNN-*` или пакет `Bxx` из `docs/PLAN-14D.md`, PR. GitVerse никто не трогает руками — туда уходит зеркало.
- Perplexity Computer открывает PR через свой GitHub-коннектор; ему достаточно того же `AGENTS.md`.
- Если PR «висит» без проверок — смотреть, что workflow запущен событием `pull_request` (а не `workflow_dispatch`) и что имена job'ов не изменены.
