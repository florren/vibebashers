# T242 — actual production UI

14 PNG проверены на настоящем API/DB0018, стандартный demo5000/2813signals,
Mock-only startup с BombLLM и запретом внешней сети. API ответы не подменялись.
Матрица ru/en × light/dark — четыре `*-top.png`; ru/light и en/dark дополнительно
показывают region (zoom400ms и реальный scoped сигнал), analytics, calculator,
mobile360px и night-mobile. Последняя — **явно заданная fixed night** с
reduced motion, а не естественный переход симуляции в ночь.

Source приложения00d6abf (Drawer fix15856a3; normal T241 composition f1c77fe), browser4/4 (24.9s).
Calculator снят после opacity1: fixed-панель вне hover-transformed card,
верх0/fullviewport900 и поле в viewport проверены regression.
Синтетические customer texts/run labels остаются данными; статический UI ru/en.
Серые деньги/пустое число пострадавших обозначают неизвестность, не нулевой убыток.
Проверки/хеши/границы writes: `docs/reviews/T-242-browser-proof.json`.
