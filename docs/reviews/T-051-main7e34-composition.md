# Foundation P1: актуальный main

Обычный merge `7e34ffbd33b9eaaf6dfe5f75953464d9ed118a43` в прежний `d8ce634199353dd0f2d2479677ea7831a043ba3d` дал `fa1f224`. Конфликтов нет. Новых контрактных решений, денежных лимитов и HITL policy не добавлено: включены уже merged исправления journey/fanout и синтетический CSI corpus.

На composed source прошли `make lint`: 354 frontend tests /44 files, Ruff415, mypy270, OpenAPI drift192/192. На собственной PostgreSQL16 `cx_profile_hotapply_revision` —47 integration tests за255.37с: runtime profiles, run lifecycle, personal execution, fanout projection budget и journey acceptance. Оба URL заданы в scratch с начала процесса, ENV_FILE=/dev/null; actual PG16 dump tools. Реальных LLM/Telegram/email вызовов нет.

Два gen_tasks запуска не изменили tracked files. Полный exact-head CI запускается после push; предыдущий зелёный CI не переносится автоматически на новый head. Human review PR180 по API1.5.18/DDL12+13 всё ещё ожидается; новые результаты его не заменяют.
