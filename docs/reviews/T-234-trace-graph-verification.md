# T-234 — SVG Graph: реализация и доказательства

Статус: implementation checkpoint; полный composed make test ещё ожидается. Contract-change требует human review: `T-234-trace-fanout-contract.md`. Ветка `codex/T-234-trace-graph`.

## Решения

Сохранён собственный SVG по образцу engine/GraphView: зависимости/CDN не добавлены. Детерминированная фазовая раскладка (before/subject/after), шесть форм и иконок для signal/incident/client/action/money/message, подписи реальных edges; mini-map показывает весь текущий набор, основной SVG виртуализирует viewport. Модель и BFS линейны по V+E; посещённое хранится на уровне TracePage (переживает смену объекта и режима), заливка/пунктир и галочка, выбранное — статичное кольцо. Текст посещённых узлов не теряет контраст, анимации мигания нет.

Subject не содержит event_id в старом DTO. Единственный неизвестный endpoint отфильтрованных assembler edges может быть subject; optional actual group anchor подтверждает его. Несколько неизвестных/противоречивых endpoints → безопасный отказ от этих рёбер, без выдумывания центра. Подсветка — только найденный directed BFS path до реального terminal.event_ref; сохранённый outcome без связного пути показан с явной подписью. Ожидаемые шаги остаются отдельными пунктирными подписями DTO, не событиями/рёбрами.

URL хранит mode=graph и focus; неизвестный mode безопасно оставляет Columns. Новый Graph по умолчанию current; all/положительный ID выбираются явно, точный scope передаётся и базовому Trace, и /relations, и при центрировании. Legacy Columns сохраняет прежний defaultall; переключение не сбрасывает keyOnly/выбранный scope. Инвалидация trace использует существующие WS topics; добавлена на runs (смена current/reset), новых topics нет.

Группы с фактическими anchor/phase раскрываются страницами50 до всех N; предыдущая/следующая страницы и список выбора всех элементов, cache старых страниц gcTime0. В DOM остаётся базовый набор и текущая страница, не все N. Для legacy groups без anchor полное раскрытие недоступно с честным объяснением. Ошибка HTTP не превращается в пустой успешный ответ.

Keyboard: стрелки/[ ] — roving выбор + pan + focus, Home — subject, End — известный terminal, Enter/Space/click — центрирование по настоящему links.trace. Первичная mobile область центрируется на выбранном узле, не на пустой before-колонке. Справа немодальный accordion Summary/Relations/Data/Navigate, на mobile снизу; details-content 400ms (reduced-motion отключает), Data показывает исключительно уже маскированную Trace-проекцию, без загрузки AgentStep/raw prompts/responses.

## Проверено

- Targeted Trace unit:14 passed. В том числе ambiguous/no path/cycles/actualanchor/dedup,300-node model (<100ms), полный UIwalk1001член/21страница, numeric/current/all/legacy default, сохранение Columns, keyboard→center/URL, ошибки/legacygroups. На полном suite scoped timeout21-последовательной-пагинации15с (вместо global5с); assertions всех1001 и отдельные строгие performance budgets сохранены.
- make lint:175 frontend passed; Ruff346files/mypy253/drift192 green. Предыдущий общий прогон обнаружил timeout пагинации под одновременной CPU-нагрузкой; после scoped15с весь suite green.
- Production Playwright:7/7 passed7,7с — ru/en ×light/dark,390pxmobilebothlangs/themes,300syntheticUI nodes: <15 DOMnodes, render<3s, keyboardpan<1s, no globaloverflow>2px. Six screenshots +stress, CSS400ms/staticring, focus/realhref centering/visited/pagination allchecked. UI300 stress явно synthetic и не расширяет API after≤200.
- Оба productionbuild прошли. Существующий bundle-size warning и DemoMenu fast-refresh warning без новых ошибок.
- Actual PG scenario regression:1 passed7,38с: сценарии1/6/8 созданы через нормальный injector+agent Mock; затем6TraceGET, все actualedges, инвариантsubjectalias, maskedDTO, fingerprintsalltables unchanged, BombLLM0.
- Actual productionUI/API/PG:24 variants (3scenarios ×signal/incident ×ru/en ×light/dark),24PNG, realclick-to-center+runScope+visited; APIмоков нет, толькоGET, pageerrors0, externalbrowserrequests0, all85applicationtablefingerprintsunchanged, BombLLM0. APP_ENV=test отключает фоновые writers/Simulator, поэтому shell GET /api/sim/state=503 ожидаем; Trace/relations работают реально. Live WS progression/real GigaChat здесь не проверялись и не заявлены.

Артефакты: `frontend/test-results/trace-graph-*/*.png` (7), `/tmp/vibebashers-t234-real-browser/*.png` (24) и proof.json; `/tmp/vibebashers-t234-real-scenarios.json`, `/tmp/vibebashers-t234-real-browser-integrity.json`; логи `/tmp/vibebashers-t234-{lint-final,browser-final4,build,real-scenarios}.log`. Screenshots доступны локально для прикрепления в PR, не закоммичены бинарниками.

## Осталось для приёмки

Normal merge актуального main (сохранить T-109 provenance/i18n), один полный make test composed ветки, генераторы/idempotence и итоговый отчёт. Human contract review AGENTS§7 обязателен до merge; generic DoD real GigaChat требует отдельно разрешённой ограниченной live проверки (эта карточка read-only, внешние calls не выполнялись). Статус карточки in_progress до выполнения gates.
