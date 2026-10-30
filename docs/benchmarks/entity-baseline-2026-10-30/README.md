# Проверки 30.10.2026: фильтры, экономика, старый baseline

Изолированный PostgreSQL 16, mock/replay без живых LLM-ключей. Рабочая БД не использовалась.

- `make lint`: ruff, format, mypy — успешно; OpenAPI drift 187/187.
- Полный `make test`: unit 601 passed/17 skipped, integration 141 passed/2 skipped,
  scenarios 22 passed/2 skipped. После добавления последних регрессий полный unit-прогон:
  603 passed/17 skipped; новые prepare/provenance/preview/filter-тесты — 7 passed.
- Финансовые регрессии, совместный фильтр кода и продуктов: 7 passed.
- Frontend: 24 файла, 134 теста; TypeScript, ESLint (0 ошибок), обе Vite-сборки — успешно.
  Локальный Node 26: для Vitest использован `NODE_OPTIONS=--no-experimental-webstorage`;
  CI использует Node 22. Существующее предупреждение ESLint в DemoMenu не менялось.
- `contracts_check.py`, `i18n_check.py`, `check_owners.py --allow-cross`, `git diff --check` — успешно.
- Chromium: finance/engine/compliance/manager/journey/economics/карточка экономики,
  ru/en × light/dark. 28 скриншотов рядом; выбор SIG-000001 в journey проверен во всех режимах темы/языка.
  Ошибок JavaScript нет. Скриншоты содержат только синтетический изолированный baseline.
- Реальный старый `lite.dump` (pg_dump 18.6, архив 1.16, источник PostgreSQL16) конвертирован
  pg_restore18/psql18/pg_dump16. Два последовательных restore: схема 0010, 200 клиентов,
  800 сигналов, CSI 480/480, added=0. Исходный SHA256 неизменен:
  `efd316e8b838d0e007f9120c488570c7da0dcc5641f9c8a3516b051d1f1b9193`.
- Интеграционный prepare-тест проверяет неизменность источника, повторный restore,
  отказ на непустой БД/перезаписи источника и откат после намеренной SQL-ошибки:
  маркер текущих данных сохраняется.

GigaChat не проверялся: в изолированном окружении нет ключей; новая логика не вызывает LLM.
Данные dump и реквизиты БД в Git не включены. Подготовка/recovery — `docs/BASELINE-COMPATIBILITY.md`.
