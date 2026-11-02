# T-252: production UI, настоящий backend и WebSocket

Четыре PNG сняты с production `frontend/dist` на source `18ad9fd0f8f054ae7fc371bfce06a3f531b342dc`: обычные merge main `dfbf47a` и одобренной зависимости PR167 (`42b6d3e`, error-code prefix 6→9). API/WS не подменялись. Сводка измерений — `proof-summary.json`.

- Отдельная `cx_circadian_revision`, PostgreSQL 16 / schema 0010; штатный fresh lite seed на 200 синтетических клиентов. До seed проверено 0 акторов; после seed запущен новый backend process. Реальные данные пользователей не использовались.
- `APP_ENV=dev`, `LLM_PROVIDER=mock`, `LLM_CHAIN=mock`; startup assertion проверяет единственный Mock и Mock для main/fast/twin. Внешние socket/DNS запрещены тестовым wrapper. Browser external/geo/errors — 0.
- `circadian-light-{ru,en}.png`: `morning`, сим-час06:00Z, Header09:00 Europe/Moscow; browser timezone America/New_York.
- `circadian-dark-{ru,en}.png`: `night`, сим-час17:30Z, Header20:30 Europe/Moscow. Это отдельный явный API `pause` + `jump_to`, не естественное наступление ночи за несколько минут.
- Auto `morning→noon`:9 настоящих running sim.tick при speed 60,08:30:06–08:38:06Z. За весь сценарий21 sim.tick:3 подготовительных command ticks,9 естественных,9 chunk ticks ночного jump_to.
- Ночной digest показывает настоящие public_id высокого приоритета текущего scratch-прогона, без текстов/контактов. На снимках видны честное ограничение10 и ссылка в рабочее место. Луна/звёзды opacity0.06, aria-hidden, ввод не перехватывают.

Все 4 PNG просмотрены: текст читаем, layout не обрезан, digest занимает отдельную область. Синтетические HTTP/WS regressions — отдельный источник доказательств и не выдаются за эти actual API снимки. Исторические c71/874 доказательства и original409 сохранены отдельно в `/tmp/vibebashers-t252-actual-{c71,874}/`.
