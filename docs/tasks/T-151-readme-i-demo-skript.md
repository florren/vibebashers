# T-151 — README и демо-скрипт

| Поле | Значение |
|---|---|
| Эпик | E12 Документация и защита |
| Субагент | `SA-Docs` (документация) |
| Оценка | M (1–2 дня) |
| Волна | 5 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Установка за 5 минут и сценарий демонстрации на 3–5 минут с таймингом и запасными ходами.

## Разделы ТЗ (docs/TZ.md)
§16, §18, §19

## Контракты
- —

## Зависимости
- Зависит от: [T-003](T-003-install-sh-ustanovka-odnoj-komandoj.md), [T-038](T-038-dvizhok-scenariev-yaml-i-7-demo-scenariev.md), [T-122](T-122-qr-kod-bota-zhyuri-rezhim-i-instrukcii-dlya-fina.md)
- Блокирует: [T-154](T-154-materialy-zaschity-tezisy-slajdy-opory-otvety-na.md), [T-204](T-204-demo-skript-7-8-i-3-5-minut-readme-razdelov-zhiv.md)

## Что сделать
1. README.md (ru, краткая en-секция): что это, требования, install.sh, флаги, мастер, демо-сценарии, бот и QR, офлайн-режим, устранение проблем.
2. docs/DEMO.md: раскадровка 5 минут (ключевой сценарий → карта → HITL → «Под капотом» → экономика → QR жюри), что говорить, что показывать, план Б при недоступности LLM (mock).

## Критерии приёмки
- [ ] Новый участник команды разворачивает проект по README без вопросов (проверка на второй машине).
- [ ] Демо-скрипт отрепетирован и укладывается в 5 мин.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
ручная проверка по чек-листу в docs/DEMO.md
```

## Отчёт субагента
- **Ветка:** `feat/T-151-readme-demo`
- **Сделано:** в `README.md` — краткая секция English (summary), пункт в содержании, ссылки на `docs/DEMO.md` в §1.6 и в карте документации (расширенный конспект — `docs/DEMO-SCRIPT.md` без изменений). Новый `docs/DEMO.md` — раскадровка ~5 мин (сценарии 8–10, экраны `/feed`, `/manager`, `/compliance`, `/engine`, опционально `/`), реплики, план Б `replay,mock`, ручной чек-лист.
- **Контракты:** не затронуты; `GET /api/public/bot/qr` без изменений.
- **Отклонения:** бот и QR не описаны как рабочий шаг показа (T-122/T-119 вне scope); репетиция по таймеру и установка на второй машине этой правкой не выполнялись — чекбоксы приёмки по ним не отмечены.
- **Проверки:** `python scripts/check_owners.py --base main` — код 0 (слой L1). `make lint` — код 2: ruff format `backend/app/config.py` (файл вне пакета). `make test` — код 2: `contracts_check` без модуля `pglast`; unit 171 passed; с `DATABASE_URL_TEST` integration/scenarios — 54 passed, 2 failed вне пакета (`tests/integration/test_agent.py`, сценарий 11). Чекбокс полного DoD не отмечен.
