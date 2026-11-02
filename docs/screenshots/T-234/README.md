# T-234 — реальный Graph UI: ru/en × light/dark

Четыре снимка production UI с действующим API/PostgreSQL, без API-моков. Сценарий 8 `qr_fee_public_review` записан обычным injector/agent с **Mock LLM**, затем Graph выполняет только GET. Данные синтетические, не реальные банковские записи. На узлах виден фактический бейдж `mock`.

- [Светлая, русский](trace-graph-light-ru.png)
- [Тёмная, русский](trace-graph-dark-ru.png)
- [Светлая, английский](trace-graph-light-en.png)
- [Тёмная, английский](trace-graph-dark-en.png)

Источник: итоговый actual UI/API proof от 2026-11-02, 24 варианта сценариев 1/6/8, real click-to-center/run scope/visited, page errors 0, external browser requests 0. Отпечатки всех 85 таблиц до/после совпали, BombLLM не сработал. На снимках — след инцидента `INC-000153`, синтетический запуск 4. UI source соответствует `40412fc`; merge `d1710be` меняет только redaction/backend-тесты и этот UI не затрагивает.

Полный отчёт и ограничения: [T-234 verification](../../reviews/T-234-trace-graph-verification.md). Полные 24 PNG и JSON proof сохранены в `/tmp/vibebashers-t234-real-browser/`; эти четыре PNG отслеживаются Git для review в PR.
