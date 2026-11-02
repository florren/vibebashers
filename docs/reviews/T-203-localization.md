# T-203: локализация статических подписей и уведомлений

В английских Manager/Compliance/LiveMeeting оставались hardcoded подписи
«ВСП», «стол», «Сотрудник», «с». Они переведены через общий i18n ru/en.
`public_reply` на двух языках уже существовал; добавлен отсутствовавший
`misselling_clarification` с одинаковыми placeholders `name/clarification`.
Шаблон сам не запускает отправку: HITL, решения и финансовые правила не меняются.
Сохранённые цитаты и `summary_ru` остаются исходными данными, не переводятся.

Source `77fd5c42922a8dfd62ad38a7d661ab2cc912313c`: полный `make test` exit0 —
1115 unit /18 skip, 240 integration /2 skip, 42 scenario /2 skip,
31 compliance, 173 frontend. Итого **1428 backend passed /22 skipped**.
`make lint` green:173 frontend, Ruff352, mypy251, drift191.
35 catalog unit passed0.52s, actual PG seed/template1passed5.84s,
Mock scenario09 1passed6.05s. Production build и i18n1690 green.

Production Chromium1217:12 desktop сочетаний ru/en ×light/dark ×3screens,
плюс English Manager320px light/dark.0pageerror/external/mutation attempts,
фактическая тема проверена; ширина document320px без overflow.
Отпечатки85publictables до/после совпали. Только собственная synthetic DB;
entity API не замоканы. Read-only preview загрузил настоящий sim_state,
но не запускал actors/ticks; LLM был запрещён Bomb,0calls.14PNG обеих языков/тем
и ограничения QA описаны в docs/screenshots/T-203/README.md.
Узкий viewport не выдаётся за отдельный UI смарт-часов T-188.

После ordinary merge main `dfbf47a` (состав `6fdcbf1`): `make lint` exit0 —
188 frontend, Ruff360, mypy256, drift192;85 template/startup/refund unit
passed2.92s, i18n1728 и TS generation idempotent. Это дополнительные
проверки состава, не повторный полный прогон; exact-head CI обязателен.
Реальные LLM/Telegram/email не вызывались, рабочие БД не изменялись.


## Актуальная композиция main2ed39d2

Ordinary merges main4667161/8b225d5/2ed39d2 сохранены, composition `c4d4d0a366246fe96691b484111f527a5a252e67`. Оба набора i18n и все bilingual templates сохранены; production-код дополнительно не менялся.

Новые проверки этого состава: 101 template/startup/refund/streaming unit passed2.95s; оба actualPG catalog/template tests passed9.49s на отдельной cx_t203_compose_revision. Make lint:188 frontend passed, Ruff366files, mypy257modules, drift192/192. Contracts45schemas/162paths, i18n1728keys, TS generation и205 task headers идемпотентны. Обе production-сборки проходят.

Повторный production Chromium QA на compositionc4d: все14 сочетаний (12desktop ru/en×light/dark×3screens +2English320px) прошли,0pageerror/external/mutationattempts/LLMcalls. EntityAPI настоящие, readonly preview безакторов/тиков. Исходная cx_t203_i18n_revision не пересидировалась; 85publictable fingerprints до/после совпали. Новые14PNG сохранены на прежних trackedpaths, proofJSON содержит source_revision c4d для каждого кадра. Эти результаты не подменяют полный backendrun77fd: новый полный backendrun не заявляется, exact-headCI остаётся gate.
