# T-222 — Логирование и репортинг качества: JSONL-журнал, HTTP-метрики, отчёт «что сломалось / работает не так / доработать», вкладка «Качество»

| Поле | Значение |
|---|---|
| Эпик | E11 Сценарии и тесты |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `done` |

## Цель
Люди и агенты видят по одному отчёту, где система падает (ошибки, 5xx, failed), где работает не так (правки HITL, fallback на правила, ложные алерты, проваленные сценарии) и что доработать (рекомендации с указанием, куда смотреть). docs/REPORTS.md.

## Разделы ТЗ (docs/TZ.md)
§12.2, §12.5, §16.4

## Контракты
- `api/openapi.yaml: /api/reports/quality, /api/reports/http, /api/reports/log (QualityReport, HttpStats)`

## Зависимости
- Зависит от: [T-141](T-141-testovaya-infrastruktura-backend.md), [T-142](T-142-avtotesty-7-demo-scenariev.md)
- Блокирует: —

## Что сделать
1. structlog → JSONL-файл var/log/app.jsonl (ротация), уровни, request_id; middleware HTTP: длительность, статус, счётчики по маршрутам, кольцевой буфер ошибок.
2. app/observability/quality.py: агрегаты по agent_runs/agent_steps (ошибки, fallback, латентность, токены по узлам), human_decisions (modify/reject = «работает, но не так»), SLA, scenarios.last_result, комплаенс (ложные алерты, транскрипты failed), HTTP; правила рекомендаций; индекс здоровья; Markdown.
3. API /api/reports/*; scripts/quality_report.py (make report) пишет data/reports/quality-<ts>.md/.json; вкладка «Качество» на /engine.
4. docs/REPORTS.md: как читать отчёт человеку и агенту, какие события логируются, как добавить новую проверку.

## Критерии приёмки
- [ ] GET /api/reports/quality?format=md отдаёт отчёт с разделами и рекомендациями; make report сохраняет файлы.
- [ ] Ошибки запросов и шагов агента видны в журнале и отчёте без доступа к stdout.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make report
curl -s localhost:8000/api/reports/quality?format=md | head -40
tail -f backend/var/log/app.jsonl | jq -c 'select(.level!="debug")'
```

## Отчёт субагента
- Ветка `feat/quality-reports` (cross-layer, contract-change). `backend/app/observability/`: `jsonl.py` (JSONL-приёмник structlog с ротацией, `read_tail`, `summarize`), `http.py` (middleware: request_id, латентность, статус; счётчики по маршрутам; кольцевой буфер ошибок; 501 считается отдельно от 5xx), `quality.py` (агрегаты по agent_runs/agent_steps/human_decisions/incidents/signals/followups/scenarios/compliance_alerts/transcripts + HTTP; правила `_recommend`, индекс `_health`, `render_markdown`).
- API `GET /api/reports/quality|http|log` (OpenAPI: `QualityReport`, `HttpStats`), `scripts/quality_report.py` + `make report` → `data/reports/` (gitignored), настройки `LOG_DIR/LOG_JSONL/LOG_JSONL_LEVEL`. Вкладка «Качество» на `/engine` (`QualityTab.tsx`). `docs/REPORTS.md`, ссылки в AGENTS.md §4/§11 и README.
- Тесты: `tests/unit/test_quality_report.py` (приёмник, ротация, счётчики, рекомендации, Markdown), `tests/integration/test_quality_report_db.py` (SQL на реальной схеме). Таблиц БД не добавлялось.
