# T-019: библиотека сигналов

Исходная грамматика содержит60 смысловых вариантов: по4ru/2en на10 типов.
Развёртка по4 продуктам и12 каналам даёт2880 уникальных полных шаблонов,
а не2880 независимо написанных историй. У каждой ячейки есть4ru/2en текста.
Поддерживаются сумма, относительная дата, продукт, промо и город; звонки содержат
реплики оператора, письма — тему, соцсети — hashtags/emoji. Стиль/психотип,
language≈5%en и вся вариативность детерминированы seed.

В активном seed/runtime используется выбранный channel. Старый вызов TextGen
без channel остаётся совместимым с legacy corpus и replay. Golden T-021 и
реальные записанные ответы не перегенерируются. Новых зависимостей/DDL/API нет.

В seed сначала гарантируется полная матрица480 комбинаций, затем3% строк обычного
lite/demo занимает отдельный небанковский noise pool. Шум имеет classification=null
и не создаёт инцидент; при недостатке строк он не вытесняет обязательную матрицу.
Gold сохраняется в private signals.meta.generator_hint, не в classification DTO;
read API его не публикует. Lang хранится в signals.lang также для runtime.
Существующий неполный historical classification — отдельный пробел T-020.

Проверены все960 сложных ru-шаблонов неизменённым Mock только с текстом: accuracy_type
15%. Это не оценка живой LLM. Проверки корпуса охватывают все placeholders,
bank references/аббревиатуры, URL/контакты и card-like цифры; исходные60вариантов
синтетические, без имён людей/банков.

## Проверки по версиям

На source a9fdedd выполнены unit1145/18skip и integration269/4skip с одним отказом:
историяT018 добавила74events к прежней CSV-фикстуре. Исправление родителя424cf2e
сначала проверяет экспорт всей реальной истории, затем изолирует контролируемые
1001CSVстроки; все исходные assertions сохранены. Этот тест вT019 passed6.36s.
Оставшиеся цели make test:43scenarios/2skip,31compliance,163frontend — passed.
Это фазовый прогон с targeted rerun, не один повторный монолитный запуск.

На финальном runtime/data96caa2a дополнительно29corpus unit passed1.72s
(включая последующий test-only guard),30targetedunit/PG passed40.09s под coverage,
в том числе дочерний seed и реальный World. Покрытие добавленных исполняемых
Pythonстрок относительно424cf2e —82/82=100%; SQL literal/continuation строки
не считаются исполняемыми Pythonстроками. АртефактT-019-changed-line-coverage.json.
Make lint exit0:360format,mypy252,163frontend,drift191; последующие изменения
трёх строк corpus и отдельного unit guard проверены targeted и formatter/Ruff.

Финальный demo5000 benchmark на96caa2a:21.502s включая baseline dump,
600000operations/2500signals,75noise,118en,0lang mismatches,480/480coverage,
31.8%hardtext. Генератор и PostgreSQL ограничены одними4логическимиCPU;
уPG лимит2GB. Миграция/bootstrap в время не входят. ProofT-019-demo-seed-proof.json.
Предыдущий замер24.813s/a9fdedd относится к более ранним текстам.

Тестовые БД/контейнер собственные, исходные рабочие данные/архивы не менялись.
Контейнер остановлен; source/proof сохранены. Exact-head CI остаётся обязательным
gate доmerge. T031 RNG continuation — отдельный PR173; после его merge нужен
обычный merge/проверка совместимости optionalchannel и общегоSimRng.
