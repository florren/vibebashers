# T-121: композиция с актуальным foundation/main

Обычный merge parentdebf463 (T-240+P1+main7e34ffb) в4a2c356 далd34b9883. Конфликтов нет. API1.5.20/DDL0015 и согласованная service-to-service/delivery граница не менялись. Реальных Telegram/LLM/email вызовов нет.

`make lint` EXIT0 на composed source:361frontend tests/46files, Ruff444/mypy284, bot12/5, drift192/192. На своей PostgreSQL16 cx_t121_transport_revision33native tests passed205.35с: storage/dialogue/delivery, personal execution, bounded fanout и journey acceptance. Внешний transport в тестах поддельный; оба scratch URL заданы с начала процесса, ENV_FILE=/dev/null.

Два gen_tasks запуска без изменений tracked files. После push обязателен новый exact-head CI; прежний зелёный результат не переносится на новый commit. Human API/DDL review PR184 уже получен, merge возможен только после parent183 и зелёного CI.
