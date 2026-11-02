# T242 — actual production UI

14 PNG проверены на настоящем API/DB0018, стандартный demo5000/2813signals,
Mock-only startup с BombLLM и запретом внешней сети. API ответы не подменялись.
Матрица ru/en × light/dark — четыре `*-top.png`; ru/light и en/dark дополнительно
показывают region (zoom400ms и реальный scoped сигнал), analytics, calculator,
mobile360px и night-mobile. Последняя — **явно заданная fixed night** с
reduced motion, а не естественный переход симуляции в ночь.

Runtime source833690 (API24+customer-view18); handoff81066a8 byte-identical runtime, browser5/5 (27.7s).
Calculator снят после opacity1: fixed-панель вне hover-transformed card,
верх0/fullviewport900 и поле в viewport проверены regression.
Синтетические customer texts/run labels остаются данными; статический UI ru/en.
Серые KPI деньги/пустое число пострадавших обозначают неизвестность. Calculator PNG показывает готовый serverpreview для явного сценарного ввода2; это не сохранённый ущерб. Все31rates также проверены через UI; трехdecimalcatalog rates передаются без изменения, result округляет сервер.
Проверки/хеши/границы writes: `docs/reviews/T-242-browser-proof.json`.
