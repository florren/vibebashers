# T-234 — SVG Graph: реализация и проверка

Реализован режим Graph и полное read-only раскрытие N связанных событий. Ветка `codex/T-234-trace-graph`, normal merge с main `f2ac951` (сохранены T-109 provenance и i18n). Contract-change OpenAPI 1.5.16 требует human review AGENTS.md §7 до merge: `T-234-trace-fanout-contract.md`. Карточка остаётся `in_progress` до внешних gates, перечисленных ниже.

## Решения интерфейса

Собственный SVG по образцу engine/GraphView, без зависимостей/CDN. Детерминированная раскладка before/subject/after, шесть форм и иконок signal/incident/client/action/money/message по семантике события, подписи реальных edges. Mini-map показывает текущий набор, основной SVG виртуализирует viewport. Модель и BFS линейны по V+E; подсветка только найденного directed path до actual terminal.event_ref, без выдумывания пути к сохранённому outcome. Посещённое переживает смену объекта/режима: приглушённая заливка, пунктир и галочка; выбранное — статичное кольцо, текст сохраняет контраст.

Subject не содержит event_id в старом DTO. Только единственный неизвестный endpoint отфильтрованных assembler edges может быть subject; optional actual group anchor подтверждает его. Несколько неизвестных/противоречивых endpoints → безопасный отказ от этих рёбер. Если anchor группы за пределами окна before40/after200, все page items доступны, скрытые edges явно помечены; ссылка открывает реальный parent Trace с тем же scope. Недоступный узел/phase не придумываются.

URL хранит mode=graph/focus/run_id, неизвестный mode оставляет Columns. Graph default=current; all/положительный ID выбираются явно, точный scope передаётся в Trace, relations и center navigation. Legacy Columns сохраняет defaultall; переключение не сбрасывает keyOnly/выбранный scope. Новых WS topics нет, trace инвалидируется также по runs (смена current/reset).

Группы с actual anchor/phase раскрываются страницами50 до всех N, есть Previous/Next и выбор каждого элемента. Старые страницы не накапливаются в DOM/cache (gcTime0); bookmark cursors нужны для Previous. Legacy группы без anchor показывают честное ограничение. Ошибка HTTP не маскируется успешным пустым результатом. Ожидаемые шаги остаются отдельными пунктирными подписями DTO, не событиями/рёбрами.

Keyboard: стрелки/[ ] — roving selection + pan/focus; Home — subject, End — известный terminal; Enter/Space/click центрируют по настоящему links.trace. На mobile первая область центрируется на выбранном объекте, а не пустой before-колонке. Справа немодальный accordion Summary/Relations/Data/Navigate, на mobile снизу; details-content 400ms, reduced-motion отключает анимацию. Data — исключительно маскированная Trace-проекция; AgentStep/raw prompts/responses не запрашиваются. Полные заголовки/refs доступны через aria/title/inspector, SVG-подписи ограничены узлом.

## Проверено

- Полный composed `make test` до последнего bounded ref guard: **backend 1406 passed /22 skipped** (unit1089, integration244, scenarios42, compliance31), **frontend188 passed**. Integration1087,21с, scenarios182,88с, compliance87,37с. Live/dependency skips не скрывались.
- После guard: **53 targeted unit/PG passed**, 48,82с, включая все затронутые fullN/scope/PII/real-scenario cases и новые boundaries. Общий parser/старый Trace не изменён. Полный backend после этого узкого guard не повторялся по согласованному плану; PR CI остаётся обязательным gate.
- Финальный `make lint`: frontend188, Ruff353 formatted files, mypy254 source files, drift192/192 — green. Существующий DemoMenu fast-refresh warning без новых ошибок. Новая backend coverage: stdlib sys/threading.settrace, **157/159 executable lines =98,74%** fanout.py;52 passed/1 performance case deselected при tracing. Performance измерен отдельно без tracing.
- Targeted Trace UI: **17 unit passed**: ambiguous/no path/cycles/actual anchor/dedup, hidden parent, semantic public_reply/refund из step,300-node model <100ms; весь UIwalk1001/21страница, scopes/legacy modes, keyboard→center/URL, ошибки. Timeout только21 последовательной пагинации15с (для shared CPU full suite), assertions всех1001 и отдельные строгие performance budgets сохранены.
- Production Playwright: **11/11 passed**,17,0с, Graph + существующие Trace/Journey; ru/en ×light/dark и390px mobile, ring/focus/visited/center/paging/400ms, no global overflow>2px, external browser requests0.15PNG:7Graph/stress+8legacy. UI300 stress намеренно synthetic, не расширяет API after≤200.
- Отдельный production browser perf300: render261,95мс (<3с), End-pan25,88мс (<1с), main DOM6→5 узлов (<15), steady-frame p9516,8мс. Локальное измерение, не гарантия другого оборудования.
- Оба production builds прошли; существующий bundle-size warning. i18n1725 keys; sync-contracts (84ORM classes), generated TS/Pydantic/ORM/schema copies и tasks205 идемпотентны. Contracts45схем/162пути; owners `--allow-cross` в согласованных слоях.
- Actual PG: сценарии1/6/8 созданы нормальным injector+agent Mock, затем6TraceGET с actualedges/subject alias invariant, maskedDTO, all-table fingerprints unchanged/BombLLM0. Прогон включён и в full, и в post-guard targets.
- **Итоговый actual productionUI/API/PG:24 variants/24PNG**,3scenarios ×signal/incident ×ru/en ×light/dark, real click-to-center/runScope/visited. APIмоков нет, толькоGET; pageerrors0/externalbrowserrequests0, **85applicationtable fingerprints unchanged, BombLLM0**. APP_ENV=test отключает фоновые writers/Simulator, shell `/api/sim/state`503 ожидаем; Graph/Trace/relations реально читают БД. Live WS progression здесь не проверялась.

## Артефакты

- `frontend/test-results/trace-graph-*/*.png`, `frontend/test-results/trace-journey-*/*.png` —15PNG, автоматически попадают в существующий CI artifact frontend/test-results.
- `/tmp/vibebashers-t234-real-browser/*.png` —24актуальных PNG, `proof.json`; `/tmp/vibebashers-t234-real-browser-integrity.json`.
- `/tmp/vibebashers-t234-{fan-perf,ui-perf,producer-coverage,ref-boundaries,real-scenarios}.json`.
- Логи `/tmp/vibebashers-t234-{composed-test,tip-lint,final-targets,coverage-final,browser-composed-final,build-final,final-sync,real-browser-tip}.log`.

Временные servers18134/18135 остановлены, использовалась только выделенная `cx_trace_graph_revision`. Бинарные screenshots не коммитились; доступны локально/в CI для прикрепления в PR.

## Оставшиеся gates

Human contract review по AGENTS.md §7, полный PR CI и оформление/merge родителем. Generic DoD realGigaChat не заявлен выполненным: Graph строго read-only и проверялся с BombLLM, fixture generation — только Mock; внешние LLM/email/TG calls не выполнялись. Эти ограничения не являются отсутствующим UI-функционалом и не замаскированы отметкой done. Общий parser `parse('²')` записан как followup существующей T-230; новый relations endpoint защищён отдельно.
